import hashlib
import json
import os
import sqlite3
import time
from typing import Any, Dict, Optional


DB_PATH = os.path.join(os.getcwd(), "cache.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw (
            property_id TEXT,
            endpoint TEXT,
            payload_json TEXT,
            ts INTEGER,
            PRIMARY KEY(property_id, endpoint)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_limits (
            day TEXT PRIMARY KEY,
            count INTEGER
        );
        """
    )
    conn.commit()
    return conn


def cache_key_from_params(params: Dict[str, Any]) -> str:
    raw = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached(endpoint: str, key: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT payload_json FROM raw WHERE property_id=? AND endpoint=?", (key, endpoint))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def set_cached(endpoint: str, key: str, payload: Dict[str, Any]):
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "REPLACE INTO raw(property_id, endpoint, payload_json, ts) VALUES (?,?,?,?)",
        (key, endpoint, json.dumps(payload), int(time.time())),
    )
    conn.commit()
    conn.close()


def rate_limit_check_and_increment(limit_per_day: int = 100) -> bool:
    """Returns True if allowed, False if limit exceeded. Increments if allowed."""
    import datetime as _dt

    day = _dt.datetime.utcnow().strftime("%Y-%m-%d")
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT count FROM rate_limits WHERE day=?", (day,))
    row = cur.fetchone()
    current = row[0] if row else 0
    if current >= limit_per_day:
        conn.close()
        return False
    new_val = current + 1
    cur.execute("REPLACE INTO rate_limits(day,count) VALUES (?,?)", (day, new_val))
    conn.commit()
    conn.close()
    return True

