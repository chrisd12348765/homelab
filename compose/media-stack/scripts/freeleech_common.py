"""Shared plumbing for the IPT freeleech automation.

One cron guard now drives the whole pipeline — freeleech-manager.py (every 5 min). This
module is the single source of truth it builds on: qBittorrent/autobrr HTTP helpers, the
qBit state-name constants, the pool/pipeline accounting, and the two decisions that define
the policy:

  * evictable(t)              -> require an explicit tracker-verified infohash.
                                 qBittorrent's local counters do not prove IPT has
                                 credited the H&R obligation.
  * intake_allowed(pool, pipe) -> grab new freeleech ONLY while the total final size of all
                                 freeleech torrents is < 500 GB and the pipeline is under cap.

History: there used to be two cron scripts (queue-guard + ratio-pool-rotate) that each
carried their own intake decision and fought over the autobrr filter. They were merged into
one script so they can no longer disagree.
"""
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

# --- endpoints / auth (env-overridable, same defaults both old scripts used) ---
QBIT_URL = os.environ.get("QBIT_URL", "http://localhost:8080").rstrip("/")
AUTOBRR_URL = os.environ.get("AUTOBRR_URL", "http://localhost:7474").rstrip("/")
AUTOBRR_FILTER = os.environ.get("AUTOBRR_FILTER", "IPT Freeleech Ratio Builder")
AUTOBRR_ENV_FILE = os.environ.get(
    "AUTOBRR_ENV_FILE", "/home/homelab/media-stack/autobrr/.ratio-pool.env"
)
AUTOBRR_API_KEY = os.environ.get("AUTOBRR_API_KEY", "")
if not AUTOBRR_API_KEY and os.path.exists(AUTOBRR_ENV_FILE):
    for _line in open(AUTOBRR_ENV_FILE):
        _line = _line.strip()
        if _line.startswith("AUTOBRR_API_KEY="):
            AUTOBRR_API_KEY = _line.split("=", 1)[1].strip().strip('"').strip("'")

# --- pool identity ---
CATEGORY = "ipt-freeleech"
SAVE_PATH = "/data/downloads/ipt-freeleech"  # qBit container view of the save path
GB = 1000 ** 3

# --- canonical qBit state sets ---
DL_STATES = {"downloading", "forcedDL", "metaDL", "stalledDL", "queuedDL"}
PAUSED_STATES = {"pausedDL", "stoppedDL", "stopped"}
# every state that counts toward the freeleech download "pipeline" (active + stopped/queued)
ALL_DL_STATES = DL_STATES | PAUSED_STATES
# states where the torrent is still pulling data — never evict mid-download
ACTIVE_DL_STATES = {
    "downloading", "forcedDL", "metaDL", "stalledDL", "queuedDL",
    "checkingDL", "checkingResumeData", "allocating", "moving",
}

# --- budget / caps (env-overridable) ---
TARGET_GB = float(os.environ.get("FREELEECH_TARGET_GB", "500"))      # intake stops at/above this
MAX_FREELEECH_QUEUED = int(os.environ.get("MAX_FREELEECH_QUEUED", "6"))   # max in any DL state
MAX_FREELEECH_DL = int(os.environ.get("MAX_FREELEECH_DL", "3"))           # max actively downloading

# The tracker credited only ~335h for torrents this client removed at ~342h.
# No fixed local-time buffer can prove a tracker-side obligation is complete.
# Keep a manual, tracker-verified allowlist outside the repo; empty by default.
VERIFIED_HASHES_FILE = os.environ.get(
    "FREELEECH_VERIFIED_HASHES_FILE",
    "/home/homelab/media-stack/autobrr/ipt-cleared-hashes.txt",
)


def verified_hashes():
    try:
        with open(VERIFIED_HASHES_FILE, encoding="ascii") as stream:
            return {line.strip().lower() for line in stream
                    if len(line.strip()) == 40 and all(c in "0123456789abcdef" for c in line.strip().lower())}
    except FileNotFoundError:
        return set()


def consume_verified_hashes(hashes):
    """Use each tracker clearance once, before asking qBittorrent to delete."""
    if not hashes:
        return
    with open(VERIFIED_HASHES_FILE, encoding="ascii") as stream:
        lines = stream.readlines()
    directory = os.path.dirname(VERIFIED_HASHES_FILE)
    fd, temp_path = tempfile.mkstemp(prefix=".ipt-cleared-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.writelines(line for line in lines if line.strip().lower() not in hashes)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, VERIFIED_HASHES_FILE)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _request_retry(req, timeout=30, retries=3, backoff=5):
    """urlopen with retries so a transient qBit/autobrr blip doesn't abort a whole run.

    Returns (status, decoded_body). `req` may be a URL string or a Request object.
    """
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, response.read().decode()
        except urllib.error.URLError as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise last


def qbit_get(path, params=None):
    """GET a qBit API path and return parsed JSON."""
    url = f"{QBIT_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return json.loads(_request_retry(url, timeout=30)[1])


def qbit_post(path, data):
    """POST form-encoded data to a qBit API path. Returns (status, body)."""
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        f"{QBIT_URL}{path}",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return _request_retry(req, timeout=60)


def get_freeleech_torrents():
    """All torrents in the freeleech category."""
    return qbit_get("/api/v2/torrents/info", {"category": CATEGORY})


def pool_size_bytes(torrents):
    """Sum of FINAL sizes for freeleech torrents at the safe save path (the logical budget).

    `size` is qBit's total torrent size — reported in full from the moment of grab, even at
    0% progress — so this is the total/final size of everything in the pool, which is exactly
    what the 500 GB intake gate measures against.
    """
    return sum(
        int(t.get("size") or 0)
        for t in torrents
        if t.get("category") == CATEGORY
        and (t.get("save_path") or "").rstrip("/") == SAVE_PATH
    )


def freeleech_pipeline_count(torrents):
    """Count freeleech torrents in any DL-related state (active + stopped/queued)."""
    return sum(
        1
        for t in torrents
        if t.get("category") == CATEGORY and t.get("state") in ALL_DL_STATES
    )


def is_safe_path(t):
    """Guard: only ever delete data that actually lives under the freeleech save path."""
    save_path = (t.get("save_path") or "").rstrip("/")
    content_path = (t.get("content_path") or "")
    return save_path == SAVE_PATH and content_path.startswith(SAVE_PATH + "/")


def cleared_for_eviction(t, cleared_hashes=None):
    """Only a hash checked against IPT's own cleared list may be deleted."""
    if cleared_hashes is None:
        cleared_hashes = verified_hashes()
    return (t.get("hash") or "").lower() in cleared_hashes


def evictable(t, cleared_hashes=None):
    """A freeleech torrent that is safe to delete right now: in our category, at the safe
    path, has data, NOT actively downloading, and has cleared its H&R obligation."""
    if t.get("category") != CATEGORY:
        return False
    if not is_safe_path(t):
        return False
    if (t.get("state") or "") in ACTIVE_DL_STATES:
        return False
    if int(t.get("size") or 0) <= 0:
        return False
    return cleared_for_eviction(t, cleared_hashes)


def intake_allowed(pool_gb, pipeline_n):
    """Enable autobrr freeleech intake ONLY while the total final size is under the 500 GB
    target AND the pipeline is under cap.

    Single hard threshold, no hysteresis: a grab commits the torrent's full size to the pool
    immediately, so the pool can't flap back and forth across 500 GB the way a still-filling
    download would — once a grab pushes it over, it stays over until eviction frees space.
    """
    return pool_gb < TARGET_GB and pipeline_n < MAX_FREELEECH_QUEUED


# --- autobrr filter control ---
def autobrr_get_filter():
    """Return the filter dict for AUTOBRR_FILTER, or None if missing/unauthed/ambiguous."""
    if not AUTOBRR_API_KEY:
        return None
    req = urllib.request.Request(
        f"{AUTOBRR_URL}/api/filters", headers={"X-API-Token": AUTOBRR_API_KEY}
    )
    try:
        _, body = _request_retry(req)
        filters = json.loads(body)
        matches = [
            f
            for f in (filters if isinstance(filters, list) else filters.get("data", []))
            if f.get("name") == AUTOBRR_FILTER
        ]
        if len(matches) == 1:
            return matches[0]
        print(f"  autobrr: filter '{AUTOBRR_FILTER}' not found or ambiguous ({len(matches)})")
    except Exception as exc:
        print(f"  autobrr_get_filter error: {exc}")
    return None


def autobrr_set_enabled(enabled):
    """Enable/disable the freeleech filter via PATCH. Idempotent; never raises."""
    enabled = bool(enabled)
    if not AUTOBRR_API_KEY:
        print("  autobrr: no API key, skipping toggle")
        return
    f = autobrr_get_filter()
    if f is None:
        return
    if f.get("enabled") == enabled:
        print(f"  autobrr: filter already {'enabled' if enabled else 'disabled'}, no change")
        return
    body = json.dumps({"enabled": enabled}).encode()
    req = urllib.request.Request(
        f"{AUTOBRR_URL}/api/filters/{f['id']}",
        data=body,
        headers={"X-API-Token": AUTOBRR_API_KEY, "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        status, _ = _request_retry(req)
        print(f"  autobrr: filter {'enabled' if enabled else 'disabled'} (HTTP {status})")
    except Exception as exc:
        print(f"  autobrr: toggle error: {exc}")
