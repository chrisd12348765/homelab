#!/usr/bin/env python3
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "60"))
QBIT_URL = os.environ.get("QBIT_URL", "http://gluetun:8080")
BAD_EXTENSIONS = tuple(
    ext.strip().lower() for ext in os.environ.get("BAD_EXTENSIONS", ".exe,.scr").split(",") if ext.strip()
)
TITLE_DANGEROUS_EXT_RE = re.compile(
    r"(?:^|[\\/\s\[\](){}_-])[^\\/]*?(?:" + "|".join(re.escape(ext) for ext in BAD_EXTENSIONS) + r")$",
    re.IGNORECASE,
)

APPS = {
    "sonarr": {
        "base_url": os.environ.get("SONARR_URL", "http://sonarr:8989"),
        "config_path": os.environ.get("SONARR_CONFIG", "/config/sonarr/config.xml"),
    },
    "radarr": {
        "base_url": os.environ.get("RADARR_URL", "http://radarr:7878"),
        "config_path": os.environ.get("RADARR_CONFIG", "/config/radarr/config.xml"),
    },
}


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def load_api_key(config_path: str) -> str:
    root = ET.parse(config_path).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"Missing ApiKey in {config_path}")
    return api_key.strip()


def ensure_api_key(app_name: str) -> str:
    """Load the app's API key lazily, on demand.

    Done per-poll instead of eagerly at import so a transient unreadable/locked config.xml
    (e.g. the arr app rewriting it, or the volume not mounted yet at container start) just
    logs a failed poll and retries next cycle, instead of crashing the process and
    crashlooping the whole container.
    """
    app = APPS[app_name]
    if not app.get("api_key"):
        app["api_key"] = load_api_key(app["config_path"])
    return app["api_key"]


def fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def delete_queue_item(app_name: str, item_id: int, reason: str) -> None:
    app = APPS[app_name]
    params = urllib.parse.urlencode(
        {
            "removeFromClient": "true",
            "blocklist": "true",
            "skipRedownload": "false",
            "apikey": app["api_key"],
        }
    )
    url = f"{app['base_url']}/api/v3/queue/{item_id}?{params}"
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req, timeout=20):
        pass
    log(f"{app_name}: removed queue item {item_id} ({reason}) and triggered replacement search")


def get_all_queue_records(app_name: str) -> List[dict]:
    app = APPS[app_name]
    page = 1
    page_size = 250
    records: List[dict] = []
    while True:
        params = urllib.parse.urlencode({"apikey": app["api_key"], "page": page, "pageSize": page_size})
        url = f"{app['base_url']}/api/v3/queue?{params}"
        data = fetch_json(url)
        page_records = data.get("records", [])
        records.extend(page_records)
        if len(records) >= data.get("totalRecords", 0) or not page_records:
            return records
        page += 1


def has_dangerous_file_extension(name: str) -> bool:
    lower = name.lower()
    basename = lower.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return any(basename.endswith(ext) for ext in BAD_EXTENSIONS)



def title_looks_like_dangerous_file(name: str) -> bool:
    lower = name.lower()
    basename = lower.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return bool(TITLE_DANGEROUS_EXT_RE.search(basename))


def torrent_files(download_id: str, cache: Dict[str, List[dict]]) -> List[dict]:
    if download_id in cache:
        return cache[download_id]
    params = urllib.parse.urlencode({"hash": download_id})
    url = f"{QBIT_URL}/api/v2/torrents/files?{params}"
    files = fetch_json(url)
    # Only cache a real, non-empty file list. A not-ready torrent (metadata not yet
    # fetched) or a qBit error object yields []/non-list; caching that would mark the
    # torrent "clean" for the rest of the process's life. Return [] WITHOUT caching so the
    # next 60s poll re-checks once the file list is actually available.
    if isinstance(files, list) and files:
        cache[download_id] = files
        return files
    return []


def find_bad_reason(record: dict, qbit_cache: Dict[str, List[dict]]) -> Optional[str]:
    title = record.get("title") or ""
    if title_looks_like_dangerous_file(title):
        return f"release title matched banned extension: {title}"

    download_id = record.get("downloadId")
    if not download_id:
        return None

    for file_info in torrent_files(download_id, qbit_cache):
        name = file_info.get("name") or ""
        if has_dangerous_file_extension(name):
            return f"torrent contents matched banned extension: {name}"
    return None


log(f"starting guard; extensions={','.join(BAD_EXTENSIONS)} qbit={QBIT_URL}")

while True:
    qbit_cache: Dict[str, List[dict]] = {}
    for app_name in APPS:
        try:
            ensure_api_key(app_name)
            for record in get_all_queue_records(app_name):
                # Isolate per-record failures so one flaky qBit/file-list call doesn't skip
                # checking every remaining item in this app's queue for the cycle.
                try:
                    reason = find_bad_reason(record, qbit_cache)
                except Exception as exc:
                    log(f"{app_name}: skip record {record.get('id')}: {exc}")
                    continue
                if reason:
                    try:
                        delete_queue_item(app_name, int(record["id"]), reason)
                    except urllib.error.HTTPError as exc:
                        body = exc.read().decode("utf-8", errors="replace")
                        log(f"{app_name}: failed removing queue item {record.get('id')}: HTTP {exc.code} {body}")
        except Exception as exc:
            log(f"{app_name}: poll failed: {exc}")
    time.sleep(POLL_SECONDS)
