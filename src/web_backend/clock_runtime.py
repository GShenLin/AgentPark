import time
from typing import Any


CLOCK_RUNNING_KEY = "_clock_running"
CLOCK_NEXT_FIRE_AT_KEY = "_clock_next_fire_at"
CLOCK_REMAINING_KEY = "_clock_remaining_seconds"
CLOCK_TRIGGER_COUNT_KEY = "_clock_trigger_count"


def format_clock_countdown(remaining_seconds: int) -> str:
    return f"Working: {max(0, int(remaining_seconds))}s"


def read_clock_next_fire_at(cfg: dict[str, Any]) -> float | None:
    raw_value = cfg.get(CLOCK_NEXT_FIRE_AT_KEY)
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            return float(raw_value.strip())
        except ValueError:
            return None
    return None


def clock_remaining_seconds(cfg: dict[str, Any], now_ts: float | None = None) -> int | None:
    next_fire_at = read_clock_next_fire_at(cfg)
    if next_fire_at is None:
        return None
    now = time.time() if now_ts is None else float(now_ts)
    return max(0, int(next_fire_at - now + 0.999))


def build_running_clock_snapshot(cfg: dict[str, Any], now_ts: float | None = None) -> dict[str, object]:
    if not isinstance(cfg, dict) or not bool(cfg.get(CLOCK_RUNNING_KEY)):
        return {}
    remaining = clock_remaining_seconds(cfg, now_ts=now_ts)
    if remaining is None:
        return {}
    return {
        CLOCK_REMAINING_KEY: remaining,
        "last_message": format_clock_countdown(remaining),
        "state": "working",
    }
