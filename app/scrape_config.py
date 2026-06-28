"""Scrape control-plane: the inputs that drive scraping.

This is the WRITE side (uploads), distinct from the read-only /scrape data API.
Three things clients manage here, all stored in S3 under config/scrape/:

  input table  -> the list of things to scrape (a CSV/JSON file). REPLACE: a new
                  upload becomes the current table (the previous one is kept under
                  history/ for audit).
  blacklist    -> entries to never scrape.   APPEND: new entries are added to the
  whitelist    -> entries allowed to scrape.   existing set (deduplicated).

The scraper (external) reads these to decide what to do. The API only stores them.
"""
import os
import re
import tempfile
import threading
from datetime import datetime, timezone

import duckdb

from app import storage

# Max accepted input-table upload size (defense against giant uploads).
MAX_INPUT_BYTES = 50 * 1024 * 1024  # 50 MB

_PREFIX = "config/scrape"
_LIST_KEY = {"blacklist": f"{_PREFIX}/blacklist.json",
             "whitelist": f"{_PREFIX}/whitelist.json"}
_INPUT_PREFIX = f"{_PREFIX}/input_table"
_INPUT_LATEST = f"{_INPUT_PREFIX}/_latest.json"

# One lock per list so concurrent appends don't lose each other's writes.
# NOTE: this guards within a single process only. Across multiple workers/hosts
# you'd need S3 conditional writes / versioning or a real database. Good enough
# for the demo; flagged as a real production consideration.
_list_locks = {"blacklist": threading.Lock(), "whitelist": threading.Lock()}


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_filename(name: str) -> str:
    """Strip any path and keep only safe characters (no traversal into the key)."""
    base = os.path.basename(name or "upload")
    return re.sub(r"[^A-Za-z0-9._-]", "_", base) or "upload"


# ---- Blacklist / whitelist (APPEND) ----

def get_list(name: str) -> list[str]:
    data = storage.get_json(_LIST_KEY[name])
    return data.get("entries", []) if data else []


def append_list(name: str, entries: list[str]) -> dict:
    """Append entries to a list, de-duplicated, preserving order. Returns what was
    actually added plus the new total."""
    # Clean input: trim, drop blanks, dedupe within this batch (keep order).
    cleaned = list(dict.fromkeys(e.strip() for e in entries if e.strip()))
    with _list_locks[name]:
        existing = get_list(name)
        have = set(existing)
        added = [e for e in cleaned if e not in have]   # only genuinely new ones
        merged = existing + added
        storage.put_json(_LIST_KEY[name], {"entries": merged, "updated_at": _iso()})
    return {"added": len(added), "total": len(merged), "added_entries": added}


# ---- Input table (REPLACE, with history) ----

def set_input_table(filename: str, content_type: str | None, data: bytes) -> dict:
    """Validate an uploaded CSV/JSON table, store it, and make it the current one.

    Raises ValueError (-> 422) if the file type is unsupported or it doesn't parse.
    """
    safe = _safe_filename(filename)
    ext = os.path.splitext(safe)[1].lower()
    if ext not in (".csv", ".json"):
        raise ValueError("unsupported file type; upload a .csv or .json file")

    # Validate it actually parses, and learn its shape (rows/columns) via DuckDB.
    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, "upload" + ext)
        with open(local, "wb") as f:
            f.write(data)
        reader = "read_csv_auto" if ext == ".csv" else "read_json_auto"
        con = duckdb.connect()
        try:
            rows = con.execute(f"SELECT count(*) FROM {reader}('{local}')").fetchone()[0]
            cols = [d[0] for d in con.execute(
                f"SELECT * FROM {reader}('{local}') LIMIT 0").description]
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"could not parse file as {ext[1:].upper()}: {e}")
        finally:
            con.close()

    # Store the raw upload immutably under history/, then point _latest at it.
    data_key = f"{_INPUT_PREFIX}/history/{_stamp()}__{safe}"
    storage.put_bytes(data_key, data, content_type or "application/octet-stream")
    meta = {
        "key": data_key,
        "filename": safe,
        "content_type": content_type,
        "rows": int(rows),
        "columns": cols,
        "uploaded_at": _iso(),
    }
    storage.put_json(_INPUT_LATEST, meta)
    return meta


def get_input_table_meta() -> dict | None:
    return storage.get_json(_INPUT_LATEST)
