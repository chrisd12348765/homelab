#!/bin/sh
# Fail-closed guard: stop Janitorr when Jellystat has too little playback history.
#
# WHY: Janitorr's least-recently-watched deletion depends entirely on Jellystat having
# playback history. LibraryItem.historyAge = max(lastSeen, importedDate), and lastSeen is
# only ever set from Jellystat. An EMPTY-but-reachable Jellystat DB is indistinguishable
# from "nothing was ever watched" -- every item falls back to importedDate, and with
# dry-run: false at <5% free, Janitorr will silently delete by *download* date, destroying
# recently-watched media. (A hard Jellystat outage is safe on its own: Feign throws and the
# Janitorr run aborts. It's specifically the empty-but-reachable case that is destructive,
# because Jellystat itself starts blind -- see jellystat_backfill.py.) Losing media is
# irreversible; a full disk is not -- so this guard fails CLOSED: stop Janitorr rather than
# let it run against a history it can't trust, and only resume it once history is restored
# (e.g. after re-running the backfill script).
#
# Runs in the docker:cli image: only the `docker` CLI is available, no bash, no python.
#
# Env vars (set by the compose service):
#   POLL_SECONDS      poll interval in seconds (default 300)
#   MIN_HISTORY_ROWS  minimum jf_playback_activity row count to consider Janitorr safe (default 50)
#   JELLYSTAT_DB_USER postgres user for jellystat-db (default jellystat)
#   TZ                container timezone (used implicitly by date(1))

POLL_SECONDS="${POLL_SECONDS:-300}"
MIN_HISTORY_ROWS="${MIN_HISTORY_ROWS:-50}"
JELLYSTAT_DB_USER="${JELLYSTAT_DB_USER:-jellystat}"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') janitorr-stats-guard: $*"
}

is_number() {
  case "$1" in
    ''|*[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

log "starting; poll=${POLL_SECONDS}s min_history_rows=${MIN_HISTORY_ROWS} db_user=${JELLYSTAT_DB_USER}"

while true; do
  # Do not let a non-zero docker exec (db down/starting, container missing, auth failure)
  # kill the loop -- that's the "take no action" branch below, not a crash.
  count=$(docker exec jellystat-db psql -U "$JELLYSTAT_DB_USER" -d jfstat -tAc 'select count(*) from jf_playback_activity' 2>/dev/null)
  count=$(printf '%s' "$count" | tr -d '[:space:]')

  if ! is_number "$count"; then
    log "jellystat-db unreachable or not ready (empty/non-numeric result); taking no action"
  else
    running=$(docker inspect -f '{{.State.Running}}' janitorr 2>/dev/null)

    if [ "$count" -lt "$MIN_HISTORY_ROWS" ]; then
      if [ "$running" = "true" ]; then
        log "!!! jf_playback_activity has only ${count} rows (< ${MIN_HISTORY_ROWS} threshold) -- Janitorr would delete by IMPORT date, not watch history. Stopping janitorr. !!!"
        docker stop janitorr >/dev/null 2>&1
      fi
      # else: already stopped, stay quiet -- don't re-log every cycle.
    else
      if [ "$running" = "false" ]; then
        log "jf_playback_activity has ${count} rows (>= ${MIN_HISTORY_ROWS} threshold) -- history restored, starting janitorr."
        docker start janitorr >/dev/null 2>&1
      fi
      # else: already running with healthy history -- the common case, stay quiet. This
      # container's logs are read by the dashboard's docker-health helper, so don't spam it.
    fi
  fi

  sleep "$POLL_SECONDS"
done
