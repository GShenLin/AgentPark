from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import os
import sqlite3
import threading
import time
from typing import Any, Callable
import zlib


CACHE_SCHEMA_VERSION = 1
CACHE_DIRNAME = "tickflow"
CACHE_FILENAME = "responses.sqlite3"
SQLITE_TIMEOUT_SECONDS = 10.0

_KEY_LOCKS = tuple(threading.Lock() for _ in range(64))


class TickFlowCacheError(RuntimeError):
    pass


@dataclass(frozen=True)
class CachedResponse:
    data: Any
    cache_key: str
    cache_hit: bool
    fetched_at: str
    expires_at: str | None


def get_or_fetch(
    workspace_root: str,
    operation: str,
    request: dict[str, Any],
    fetch: Callable[[], Any],
) -> CachedResponse:
    cache_path = _cache_path(workspace_root)
    key = _cache_key(operation, request)
    now = time.time()
    cached = _read(cache_path, key, now)
    if cached is not None:
        return cached

    lock = _key_lock(key)
    with lock:
        now = time.time()
        cached = _read(cache_path, key, now)
        if cached is not None:
            return cached

        data = fetch()
        fetched_timestamp = time.time()
        fetched_at = _isoformat(fetched_timestamp)
        ttl = _cache_ttl_seconds(operation, request, fetched_timestamp)
        expires_timestamp = None if ttl is None else fetched_timestamp + ttl
        expires_at = None if expires_timestamp is None else _isoformat(expires_timestamp)
        _write(
            cache_path,
            key=key,
            operation=operation,
            request=request,
            data=data,
            fetched_at=fetched_at,
            fetched_timestamp=fetched_timestamp,
            expires_timestamp=expires_timestamp,
        )
        return CachedResponse(
            data=data,
            cache_key=key,
            cache_hit=False,
            fetched_at=fetched_at,
            expires_at=expires_at,
        )


def _cache_path(workspace_root: str) -> str:
    root = os.path.abspath(str(workspace_root or "").strip())
    if not root:
        raise TickFlowCacheError("TickFlow cache requires a workspace root.")
    return os.path.join(root, ".cache", CACHE_DIRNAME, CACHE_FILENAME)


def _cache_key(operation: str, request: dict[str, Any]) -> str:
    payload = {
        "version": CACHE_SCHEMA_VERSION,
        "operation": operation,
        "request": request,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _key_lock(key: str) -> threading.Lock:
    return _KEY_LOCKS[int(key[:8], 16) % len(_KEY_LOCKS)]


def _connect(path: str) -> sqlite3.Connection:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        connection = sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SECONDS)
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS responses (
                cache_key TEXT PRIMARY KEY,
                operation TEXT NOT NULL,
                request_json TEXT NOT NULL,
                data_blob BLOB NOT NULL,
                fetched_at TEXT NOT NULL,
                fetched_timestamp REAL NOT NULL,
                expires_timestamp REAL
            )
            """
        )
        return connection
    except (OSError, sqlite3.Error) as exc:
        raise TickFlowCacheError(f"Could not open TickFlow cache: {exc}") from exc


def _read(path: str, key: str, now: float) -> CachedResponse | None:
    try:
        with _connect(path) as connection:
            row = connection.execute(
                """
                SELECT data_blob, fetched_at, expires_timestamp
                FROM responses
                WHERE cache_key = ?
                """,
                (key,),
            ).fetchone()
            if row is None:
                return None
            data_blob, fetched_at, expires_timestamp = row
            if expires_timestamp is not None and float(expires_timestamp) <= now:
                connection.execute("DELETE FROM responses WHERE cache_key = ?", (key,))
                return None
            return CachedResponse(
                data=json.loads(zlib.decompress(bytes(data_blob)).decode("utf-8")),
                cache_key=key,
                cache_hit=True,
                fetched_at=str(fetched_at),
                expires_at=None if expires_timestamp is None else _isoformat(float(expires_timestamp)),
            )
    except (json.JSONDecodeError, OSError, sqlite3.Error, TypeError, ValueError, zlib.error) as exc:
        raise TickFlowCacheError(f"Could not read TickFlow cache entry: {exc}") from exc


def _write(
    path: str,
    *,
    key: str,
    operation: str,
    request: dict[str, Any],
    data: Any,
    fetched_at: str,
    fetched_timestamp: float,
    expires_timestamp: float | None,
) -> None:
    try:
        request_json = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        data_blob = sqlite3.Binary(
            zlib.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        )
        with _connect(path) as connection:
            connection.execute(
                """
                INSERT INTO responses (
                    cache_key,
                    operation,
                    request_json,
                    data_blob,
                    fetched_at,
                    fetched_timestamp,
                    expires_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    operation = excluded.operation,
                    request_json = excluded.request_json,
                    data_blob = excluded.data_blob,
                    fetched_at = excluded.fetched_at,
                    fetched_timestamp = excluded.fetched_timestamp,
                    expires_timestamp = excluded.expires_timestamp
                """,
                (
                    key,
                    operation,
                    request_json,
                    data_blob,
                    fetched_at,
                    fetched_timestamp,
                    expires_timestamp,
                ),
            )
    except (TypeError, ValueError, OSError, sqlite3.Error) as exc:
        raise TickFlowCacheError(f"Could not write TickFlow cache entry: {exc}") from exc


def _cache_ttl_seconds(operation: str, request: dict[str, Any], now: float) -> float | None:
    if operation == "quotes":
        return 10.0
    if operation == "depth":
        return 5.0
    if operation == "intraday":
        return max(1.0, 60.0 - (now % 60.0))
    if operation == "klines":
        end_time = request.get("end_time")
        if isinstance(end_time, int) and end_time < int(now * 1000) - _period_milliseconds(request.get("period")):
            return None
        period = str(request.get("period") or "1d")
        if period.endswith("m") and period[:-1].isdigit():
            return max(60.0, float(int(period[:-1]) * 60))
        return 6 * 60 * 60.0
    if operation in {"financials", "instruments", "universes.list", "universes.get"}:
        return 24 * 60 * 60.0
    return 60.0


def _period_milliseconds(value: object) -> int:
    period = str(value or "1d")
    if period.endswith("m") and period[:-1].isdigit():
        return int(period[:-1]) * 60 * 1000
    if period.endswith("d") and period[:-1].isdigit():
        return int(period[:-1]) * 24 * 60 * 60 * 1000
    return 24 * 60 * 60 * 1000


def _isoformat(timestamp: float) -> str:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).isoformat()
