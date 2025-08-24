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
        CREATE TABLE IF NOT EXISTS llm_cache (
            prompt_hash TEXT PRIMARY KEY,
            response_json TEXT,
            ts INTEGER
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


def get_cached(endpoint: str, key: str, ttl_hours: int = 24) -> Optional[Dict[str, Any]]:
    """Get cached API response if within TTL."""
    conn = _connect()
    cur = conn.cursor()
    
    # Calculate cutoff timestamp for TTL
    cutoff_ts = int(time.time()) - (ttl_hours * 3600)
    
    cur.execute(
        "SELECT payload_json FROM raw WHERE property_id=? AND endpoint=? AND ts > ?", 
        (key, endpoint, cutoff_ts)
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return json.loads(row[0])


def set_cached(endpoint: str, key: str, payload: Dict[str, Any]):
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "REPLACE INTO raw(property_id, endpoint, payload_json, ts) VALUES (?,?,?,?)",
        (key, endpoint, json.dumps(payload), int(time.time())),
    )
    conn.commit()
    conn.close()


def get_llm_cached(prompt: str, system: str = "", ttl_hours: int = 24) -> Optional[Dict[str, Any]]:
    """Get cached LLM response if within TTL."""
    # Create hash from prompt + system message for cache key
    combined = f"{system}|||{prompt}"
    prompt_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    
    conn = _connect()
    cur = conn.cursor()
    
    # Calculate cutoff timestamp for TTL
    cutoff_ts = int(time.time()) - (ttl_hours * 3600)
    
    cur.execute(
        "SELECT response_json FROM llm_cache WHERE prompt_hash=? AND ts > ?", 
        (prompt_hash, cutoff_ts)
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return json.loads(row[0])


def set_llm_cached(prompt: str, system: str = "", response: Dict[str, Any] = None):
    """Cache LLM response."""
    # Create hash from prompt + system message for cache key
    combined = f"{system}|||{prompt}"
    prompt_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "REPLACE INTO llm_cache(prompt_hash, response_json, ts) VALUES (?,?,?)",
        (prompt_hash, json.dumps(response), int(time.time())),
    )
    conn.commit()
    conn.close()


def clear_all_cache():
    """Clear all cached data (API and LLM)."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM raw")
    cur.execute("DELETE FROM llm_cache")
    conn.commit()
    conn.close()


def clear_llm_cache():
    """Clear only LLM cached data."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM llm_cache")
    conn.commit()
    conn.close()


def clear_api_cache():
    """Clear only API cached data."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM raw")
    conn.commit()
    conn.close()


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    conn = _connect()
    cur = conn.cursor()
    
    # Count API cache entries
    cur.execute("SELECT COUNT(*) FROM raw")
    api_count = cur.fetchone()[0]
    
    # Count LLM cache entries
    cur.execute("SELECT COUNT(*) FROM llm_cache")
    llm_count = cur.fetchone()[0]
    
    # Get size of cache file
    cache_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    
    conn.close()
    
    return {
        "api_cache_entries": api_count,
        "llm_cache_entries": llm_count,
        "cache_file_size_bytes": cache_size,
        "cache_file_path": DB_PATH
    }


def rate_limit_check_and_increment(limit_per_day: int = 100) -> bool:
    """Returns True if allowed, False if limit exceeded. Increments if allowed."""
    import datetime as _dt

    day = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
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

