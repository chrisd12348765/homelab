#!/usr/bin/env python3
"""
Seed Jellystat's playback history from Jellyfin's own UserData table.

Jellystat only records plays that happen while it is running, and its only import
path is the Jellyfin "Playback Reporting" plugin (not installed here). Without a
seed, Janitorr's LibraryItem.historyAge falls back to the *arr import date, so a
show watched recently but downloaded years ago would be treated as ancient and
deleted. Jellyfin has tracked LastPlayedDate per user since Feb 2026; this
replays that into jf_playback_activity.

Row shape mirrors Jellystat's own ActivityMonitor.js:
    NowPlayingItemId = SeriesId || Id
i.e. episode plays are filed under the SERIES id, which is what Janitorr looks up
when clients.jellystat.whole-tv-show is true. Movies file under their own id.

Rows are written with imported=true so they can be identified and removed:
    DELETE FROM jf_playback_activity WHERE imported = true AND "Client" = 'Jellyfin UserData backfill';

Self-contained: copies jellyfin.db out of the jellyfin container itself (via
`docker cp`) into a scratch temp file and removes it when done, so this can be run
standalone on the media-server host with no pre-staged /tmp/jf.db. Idempotent: rows
already present in jf_playback_activity (matched on NowPlayingItemId/EpisodeId/UserId)
are skipped, so re-running (e.g. after Jellyfin racks up more watch history, or just to
double check) only inserts what's new. Requires nothing but the stdlib -- Postgres access
goes through `docker exec jellystat-db psql`, not a Python driver.
"""
import csv
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid

CLIENT_TAG = "Jellyfin UserData backfill"
JELLYFIN_CONTAINER = "jellyfin"
JELLYFIN_DB_PATH_IN_CONTAINER = "/config/data/data/jellyfin.db"
JELLYSTAT_DB_CONTAINER = "jellystat-db"
JELLYSTAT_DB_USER = os.environ.get("JELLYSTAT_DB_USER", "jellystat")

COLUMNS = [
    "Id", "IsPaused", "UserId", "UserName", "Client", "DeviceName",
    "NowPlayingItemId", "NowPlayingItemName", "SeasonId", "SeriesName",
    "EpisodeId", "PlaybackDuration", "ActivityDateInserted", "PlayMethod", "imported",
]


def norm(guid):
    """Jellyfin's SQLite stores dashed uppercase GUIDs; its API (and so Jellystat)
    uses 32-char lowercase hex."""
    return guid.replace("-", "").lower() if guid else None


def psql(sql, stdin=None):
    return subprocess.run(
        ["docker", "exec", "-i", JELLYSTAT_DB_CONTAINER, "psql", "-U", JELLYSTAT_DB_USER,
         "-d", "jfstat", "-v", "ON_ERROR_STOP=1", "-c", sql],
        input=stdin, capture_output=True, text=True, check=True,
    ).stdout


def main():
    apply = "--apply" in sys.argv

    tmpdir = tempfile.mkdtemp(prefix="jellystat-backfill-")
    jf_db = os.path.join(tmpdir, "jf.db")
    out_csv = os.path.join(tmpdir, "backfill.csv")
    try:
        subprocess.run(
            ["docker", "cp", f"{JELLYFIN_CONTAINER}:{JELLYFIN_DB_PATH_IN_CONTAINER}", jf_db],
            check=True,
        )

        con = sqlite3.connect(f"file:{jf_db}?mode=ro", uri=True)
        users = dict(con.execute("select Id, Username from Users"))
        # Jellyfin keeps one UserData row per provider key (item GUID, imdb, tvdb...), so the
        # same item+user repeats. Collapse to the LATEST play per (item, user) rather than
        # whichever row the scan happens to hit first.
        rows = con.execute("""
            select u.UserId, max(u.LastPlayedDate), b.Type, b.Id, b.SeriesId, b.SeasonId,
                   b.SeriesName, b.Name, b.RunTimeTicks
            from UserData u join BaseItems b on b.Id = u.ItemId
            where u.LastPlayedDate is not null
            group by u.UserId, b.Id
        """).fetchall()
        con.close()

        # Anything already in Jellystat (it has been live and recording, or was seeded by a
        # prior run of this script) wins over a seeded row -- this is what makes re-running
        # idempotent.
        existing = set()
        for line in psql('select coalesce("NowPlayingItemId",\'\') || \'|\' || coalesce("EpisodeId",\'\') || \'|\' || coalesce("UserId",\'\') from jf_playback_activity').splitlines():
            line = line.strip()
            if line and "|" in line:
                existing.add(line)

        out, skipped_placeholder, skipped_dupe = [], 0, 0
        for user_id, last_played, typ, item_id, series_id, season_id, series_name, name, ticks in rows:
            if not typ.endswith(("Episode", "Movie")):
                skipped_placeholder += 1
                continue

            is_episode = typ.endswith("Episode")
            npid = norm(series_id) if is_episode else norm(item_id)
            if not npid:
                skipped_placeholder += 1
                continue
            eid = norm(item_id) if is_episode else None
            sid = norm(season_id) if is_episode else None
            uid = norm(user_id)

            key = f"{npid}|{eid or ''}|{uid}"
            if key in existing:
                skipped_dupe += 1
                continue
            existing.add(key)

            # Janitorr ignores any play with PlaybackDuration <= 60, so a real runtime
            # (RunTimeTicks is in 100ns units) is both truthful and above the floor.
            duration = int(ticks / 10_000_000) if ticks else 0
            duration = max(duration, 61)

            # Postgres takes at most 6 fractional digits; Jellyfin writes up to 7. UTC.
            ts = last_played.strip()
            if "." in ts:
                head, frac = ts.split(".", 1)
                ts = f"{head}.{frac[:6]}"
            ts += "+00"

            out.append({
                "Id": str(uuid.uuid4()),
                "IsPaused": "false",
                "UserId": uid,
                "UserName": users.get(user_id, "unknown"),
                "Client": CLIENT_TAG,
                "DeviceName": "Jellyfin",
                "NowPlayingItemId": npid,
                "NowPlayingItemName": name or "",
                "SeasonId": sid or "",
                "SeriesName": series_name or "",
                "EpisodeId": eid or "",
                "PlaybackDuration": duration,
                "ActivityDateInserted": ts,
                "PlayMethod": "DirectPlay",
                "imported": "true",
            })

        eps = sum(1 for r in out if r["EpisodeId"])
        print(f"jellyfin rows read      : {len(rows)}")
        print(f"skipped (placeholder)   : {skipped_placeholder}")
        print(f"skipped (already known) : {skipped_dupe}")
        print(f"to insert               : {len(out)}  ({eps} episodes, {len(out)-eps} movies)")
        print(f"distinct series/movies  : {len({r['NowPlayingItemId'] for r in out})}")
        print(f"distinct users          : {sorted({r['UserName'] for r in out})}")
        if out:
            d = sorted(r["ActivityDateInserted"] for r in out)
            print(f"date range              : {d[0]}  ->  {d[-1]}")
            print("\nsample:")
            for r in out[:2]:
                print("  ", {k: r[k] for k in ("UserName", "NowPlayingItemId", "SeriesName", "NowPlayingItemName", "PlaybackDuration", "ActivityDateInserted")})

        if not apply:
            print("\nDRY RUN — nothing written. Re-run with --apply.")
            return

        with open(out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writerows(out)

        cols = ",".join(f'"{c}"' for c in COLUMNS)
        with open(out_csv) as f:
            subprocess.run(
                ["docker", "exec", "-i", JELLYSTAT_DB_CONTAINER, "psql", "-U", JELLYSTAT_DB_USER, "-d", "jfstat",
                 "-v", "ON_ERROR_STOP=1",
                 "-c", f"\\copy jf_playback_activity ({cols}) FROM STDIN WITH (FORMAT csv, NULL '')"],
                stdin=f, check=True,
            )
        print(f"\ninserted {len(out)} rows")
        print(psql('select count(*) as total, count(distinct "NowPlayingItemId") as items from jf_playback_activity'))
    finally:
        for path in (jf_db, out_csv):
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


if __name__ == "__main__":
    main()
