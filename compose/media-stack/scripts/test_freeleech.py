#!/usr/bin/env python3
"""Unit tests for freeleech_common pure logic — the H&R safety property is the headline.

Run from the dir holding freeleech_common.py:  python3 test_freeleech.py
No network needed: only the pure decision functions are exercised.
"""
import freeleech_common as fc
import tempfile
from pathlib import Path

SP = fc.SAVE_PATH
CAT = fc.CATEGORY
HOUR = 3600

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


def torrent(**kw):
    """A freeleech torrent at the safe path, seeding, with sane defaults; override per test."""
    t = {
        "category": CAT,
        "save_path": SP,
        "content_path": SP + "/Some.Release",
        "state": "stalledUP",
        "size": 5_000_000_000,
        "ratio": 0.0,
        "seeding_time": 0,
        "downloaded": 5_000_000_000,
        "hash": "deadbeef",
        "name": "Some.Release",
    }
    t.update(kw)
    return t


# qBittorrent's 342h led to IPT recording ~335h: local counters never authorize deletion.
check("342h does not clear", not fc.cleared_for_eviction(torrent(seeding_time=342 * HOUR), set()))
check("high ratio does not clear", not fc.cleared_for_eviction(torrent(ratio=5), set()))
check("explicit tracker verification clears", fc.cleared_for_eviction(torrent(), {"deadbeef"}))
check("different hash does not clear", not fc.cleared_for_eviction(torrent(), {"cafebabe"}))

with tempfile.TemporaryDirectory() as temp_dir:
    old_path = fc.VERIFIED_HASHES_FILE
    fc.VERIFIED_HASHES_FILE = str(Path(temp_dir) / "cleared.txt")
    Path(fc.VERIFIED_HASHES_FILE).write_text("a" * 40 + "\n" + "b" * 40 + "\n")
    fc.consume_verified_hashes({"a" * 40})
    check("clearance is one-use", fc.verified_hashes() == {"b" * 40})
    fc.VERIFIED_HASHES_FILE = old_path


# ---- evictable: THE H&R-safety gate. Must be False for anything not cleared. ----
check("verified+seeding -> evictable", fc.evictable(torrent(), {"deadbeef"}))
check("verified+pausedUP -> evictable", fc.evictable(torrent(state="pausedUP"), {"deadbeef"}))
# H&R safety: uncleared is NEVER evictable
check("UNcleared -> NOT evictable", not fc.evictable(torrent(ratio=0.3, seeding_time=50 * HOUR), set()))
check("at IPT bar (1.0) -> NOT evictable", not fc.evictable(torrent(ratio=1.0), set()))
check("at IPT bar (336h) -> NOT evictable", not fc.evictable(torrent(seeding_time=336 * HOUR), set()))
# never delete mid-download even if ratio somehow high
check("cleared but downloading -> NOT evictable", not fc.evictable(torrent(state="downloading"), {"deadbeef"}))
check("cleared but stalledDL -> NOT evictable", not fc.evictable(torrent(state="stalledDL"), {"deadbeef"}))
check("cleared but checkingDL -> NOT evictable", not fc.evictable(torrent(state="checkingDL"), {"deadbeef"}))
check("cleared but moving -> NOT evictable", not fc.evictable(torrent(state="moving"), {"deadbeef"}))
# safety: wrong path / wrong category / no data
check("wrong save_path -> NOT evictable", not fc.evictable(torrent(save_path="/data/downloads/movies"), {"deadbeef"}))
check("content outside save_path -> NOT evictable",
      not fc.evictable(torrent(content_path="/data/downloads/movies/x"), {"deadbeef"}))
check("wrong category -> NOT evictable", not fc.evictable(torrent(category="movies"), {"deadbeef"}))
check("zero size -> NOT evictable", not fc.evictable(torrent(size=0), {"deadbeef"}))


# ---- intake_allowed: only grab while total final size < 500GB AND pipeline < cap ----
check("pool 499 / pipe 0 -> allow", fc.intake_allowed(499, 0))
check("pool 499.99 / pipe 5 -> allow", fc.intake_allowed(499.99, 5))
check("pool exactly 500 -> deny", not fc.intake_allowed(500, 0))
check("pool 636 -> deny", not fc.intake_allowed(636, 0))
check("pool 100 but pipe at cap -> deny", not fc.intake_allowed(100, fc.MAX_FREELEECH_QUEUED))
check("pool 100 / pipe cap-1 -> allow", fc.intake_allowed(100, fc.MAX_FREELEECH_QUEUED - 1))


# ---- is_safe_path edge: trailing slash on save_path ----
check("trailing slash save_path normalised",
      fc.is_safe_path({"save_path": SP + "/", "content_path": SP + "/X"}))
check("content_path == save_path (no child) -> unsafe",
      not fc.is_safe_path({"save_path": SP, "content_path": SP}))


# ---- pool_size_bytes / freeleech_pipeline_count over a mixed set ----
mixed = [
    torrent(size=10_000_000_000),                         # counts
    torrent(size=20_000_000_000, state="downloading"),    # counts (final size)
    torrent(size=99, category="movies"),                  # other cat, excluded
    torrent(size=99, save_path="/data/downloads/other"),  # wrong path, excluded
]
check("pool_size sums only freeleech@safepath final sizes",
      fc.pool_size_bytes(mixed) == 30_000_000_000)


print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
