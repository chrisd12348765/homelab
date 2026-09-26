#!/usr/bin/env python3
"""Single cron guard for the IPT freeleech ratio-farm. Runs every 5 min via cron.

Replaces the old pair (queue-guard.py + ratio-pool-rotate.py) with ONE script, so the two
can no longer disagree about intake and there is one place to reason about the whole pipeline.
Default is dry-run; pass --apply to actually act.

Jobs, in order:
  1. TOP-PRIORITY   any movies/tv torrent that is queued/downloading is bumped to the top of
                    the queue so Arr requests never sit behind freeleech.
  2. ACTIVE CAP     at most MAX_FREELEECH_DL freeleech torrents download at once; extras are
                    stopped (keeping the furthest-along), paused ones resumed when slots free.
  3. EVICTION       delete only hashes explicitly verified as cleared on IPT's site.
                    qBittorrent's local seeding time is insufficient evidence.
  4. PIPELINE CAP   at most MAX_FREELEECH_QUEUED freeleech in any DL state; when over, only
                    0-byte torrents (no bytes ever written -> no H&R risk) are purged.
  5. INTAKE GATE    enable the autobrr freeleech filter ONLY while the total final size of all
                    freeleech torrents is < 500 GB AND the pipeline is under cap.

Plumbing (qBit/autobrr HTTP, state constants, the evict/intake policy) lives in
freeleech_common.py next to this script.
"""
import argparse
import sys
import time

import freeleech_common as fc

REQUEST_CATEGORIES = {"movies", "tv"}


def gb(n):
    return n / fc.GB


def fmt_gb(n):
    return f"{gb(n):.1f}GB"


def hashes(torrents):
    return "|".join(t["hash"] for t in torrents)


def main():
    ap = argparse.ArgumentParser(description="IPT freeleech pipeline guard (all-in-one)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report only (default)")
    mode.add_argument("--apply", action="store_true", help="act: stop/resume/delete + toggle intake")
    args = ap.parse_args()
    dry_run = not args.apply

    print(f"=== freeleech-manager {time.strftime('%Y-%m-%dT%H:%M:%S%z')} "
          f"mode={'dry-run' if dry_run else 'apply'} ===")

    torrents = fc.qbit_get("/api/v2/torrents/info")

    # --- Job 1: top-prioritize request categories -------------------------------------------
    request_dl = [
        t for t in torrents
        if t.get("category") in REQUEST_CATEGORIES and t.get("state") in fc.DL_STATES
    ]
    if request_dl:
        print(f"top_prio: {len(request_dl)} movies/tv download(s) -> topPrio")
        for t in request_dl:
            print(f"  [{t['state']}] {t['name'][:60]}")
        if not dry_run:
            fc.qbit_post("/api/v2/torrents/topPrio", {"hashes": hashes(request_dl)})
    else:
        print("top_prio: no movies/tv downloads pending")

    # --- Job 2: freeleech concurrent-download cap -------------------------------------------
    fl_active = [t for t in torrents
                 if t.get("category") == fc.CATEGORY and t.get("state") in fc.DL_STATES]
    fl_paused = [t for t in torrents
                 if t.get("category") == fc.CATEGORY and t.get("state") in fc.PAUSED_STATES]
    print(f"freeleech_active: {len(fl_active)} active, {len(fl_paused)} paused, cap={fc.MAX_FREELEECH_DL}")

    if len(fl_active) > fc.MAX_FREELEECH_DL:
        ordered = sorted(fl_active, key=lambda t: t.get("progress", 0), reverse=True)
        pause = ordered[fc.MAX_FREELEECH_DL:]
        print(f"  pausing {len(pause)} (keeping top {fc.MAX_FREELEECH_DL} by progress)")
        for t in pause:
            print(f"    pause [{t['state']}] prog={t['progress']*100:.1f}% {t['name'][:55]}")
        if not dry_run:
            fc.qbit_post("/api/v2/torrents/stop", {"hashes": hashes(pause)})
    elif len(fl_active) < fc.MAX_FREELEECH_DL and fl_paused:
        # Resume already-started torrents to completion; that is the only way an over-budget
        # pipeline drains, and finishing also clears their IPT H&R obligation.
        slots = fc.MAX_FREELEECH_DL - len(fl_active)
        resume = sorted(fl_paused, key=lambda t: t.get("progress", 0), reverse=True)[:slots]
        print(f"  resuming {len(resume)} ({slots} slot(s) free)")
        for t in resume:
            print(f"    resume prog={t['progress']*100:.1f}% {t['name'][:55]}")
        if not dry_run:
            fc.qbit_post("/api/v2/torrents/start", {"hashes": hashes(resume)})
    else:
        print("  at or under cap, no change")

    # --- Job 3: deterministic eviction ------------------------------------------------------
    cleared_hashes = fc.verified_hashes()
    evict = [t for t in torrents if fc.evictable(t, cleared_hashes)]
    freed = sum(int(t.get("size") or 0) for t in evict)
    print(f"eviction: {len(evict)} tracker-verified ({len(cleared_hashes)} allowlisted hashes) "
          f"-> free {fmt_gb(freed)}")
    for t in evict:
        print(f"  evict size={fmt_gb(int(t.get('size') or 0))} ratio={float(t.get('ratio') or 0):.3f} "
              f"seed={int(t.get('seeding_time') or 0)/3600:.1f}h state={t.get('state')} "
              f"hash={t.get('hash','')[:12]} {t.get('name','')[:50]}")
    if evict and not dry_run:
        fc.consume_verified_hashes({t["hash"].lower() for t in evict})
        fc.qbit_post("/api/v2/torrents/delete", {"hashes": hashes(evict), "deleteFiles": "true"})
        print(f"  deleted {len(evict)} torrents, freed {fmt_gb(freed)}")
        # refresh the working set so the pipeline cap / intake gate see post-eviction reality
        torrents = fc.qbit_get("/api/v2/torrents/info")

    # --- Job 4: pipeline total cap ----------------------------------------------------------
    # Bounds how many freeleech grabs are in flight at once (bandwidth / arr starvation), on top
    # of the size gate. Only 0-byte torrents (no bytes ever written -> no H&R risk) are purged.
    fl_pipeline = [t for t in torrents
                   if t.get("category") == fc.CATEGORY and t.get("state") in fc.ALL_DL_STATES]
    print(f"pipeline: {len(fl_pipeline)} in DL state (cap={fc.MAX_FREELEECH_QUEUED})")
    if len(fl_pipeline) > fc.MAX_FREELEECH_QUEUED:
        removable = [t for t in fl_pipeline if int(t.get("downloaded") or 0) == 0]
        over = len(fl_pipeline) - fc.MAX_FREELEECH_QUEUED
        to_remove = removable[:over]
        print(f"  over cap by {over}: {len(removable)} purgeable (0 bytes), removing {len(to_remove)}")
        for t in to_remove:
            print(f"    purge 0B {t['name'][:55]}")
        if to_remove and not dry_run:
            fc.qbit_post("/api/v2/torrents/delete", {"hashes": hashes(to_remove), "deleteFiles": "true"})
            torrents = fc.qbit_get("/api/v2/torrents/info")  # refresh so the gate sees post-purge reality

    # --- Job 5: intake gate -----------------------------------------------------------------
    # pool + pipeline are read from the (post-eviction, post-purge) torrent set so the 500 GB gate
    # never counts a torrent this run already deleted.
    pool = fc.pool_size_bytes(torrents)
    pipeline_n = fc.freeleech_pipeline_count(torrents)
    want = fc.intake_allowed(gb(pool), pipeline_n)
    print(f"intake: pool={fmt_gb(pool)} target={fc.TARGET_GB:.0f}GB pipeline={pipeline_n} "
          f"cap={fc.MAX_FREELEECH_QUEUED} -> {'ENABLE' if want else 'DISABLE'}")
    if not dry_run:
        fc.autobrr_set_enabled(want)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"error={exc}", file=sys.stderr)
        sys.exit(1)
