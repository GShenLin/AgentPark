from __future__ import annotations

from src.value_parsing import parse_int_value


CLOCK_INTERVAL_DAYS_KEY = "IntervalDays"
CLOCK_INTERVAL_HOURS_KEY = "IntervalHours"
CLOCK_INTERVAL_MINUTES_KEY = "IntervalMinutes"
CLOCK_INTERVAL_SECONDS_KEY = "IntervalSeconds"

DEFAULT_CLOCK_INTERVAL_FIELDS = {
    CLOCK_INTERVAL_DAYS_KEY: "0",
    CLOCK_INTERVAL_HOURS_KEY: "0",
    CLOCK_INTERVAL_MINUTES_KEY: "1",
    CLOCK_INTERVAL_SECONDS_KEY: "0",
}

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 60 * _SECONDS_PER_MINUTE
_SECONDS_PER_DAY = 24 * _SECONDS_PER_HOUR


def _split_total_seconds(total_seconds: int) -> dict[str, str]:
    remaining = max(0, int(total_seconds))
    days, remaining = divmod(remaining, _SECONDS_PER_DAY)
    hours, remaining = divmod(remaining, _SECONDS_PER_HOUR)
    minutes, seconds = divmod(remaining, _SECONDS_PER_MINUTE)
    return {
        CLOCK_INTERVAL_DAYS_KEY: str(days),
        CLOCK_INTERVAL_HOURS_KEY: str(hours),
        CLOCK_INTERVAL_MINUTES_KEY: str(minutes),
        CLOCK_INTERVAL_SECONDS_KEY: str(seconds),
    }


def build_clock_interval_fields(cfg: dict | None) -> dict[str, str]:
    if not isinstance(cfg, dict):
        return dict(DEFAULT_CLOCK_INTERVAL_FIELDS)

    has_explicit_parts = any(
        key in cfg
        for key in (
            CLOCK_INTERVAL_DAYS_KEY,
            CLOCK_INTERVAL_HOURS_KEY,
            CLOCK_INTERVAL_MINUTES_KEY,
        )
    )
    if has_explicit_parts:
        total_seconds = (
            parse_int_value(cfg.get(CLOCK_INTERVAL_DAYS_KEY), default=0, minimum=0) * _SECONDS_PER_DAY
            + parse_int_value(cfg.get(CLOCK_INTERVAL_HOURS_KEY), default=0, minimum=0) * _SECONDS_PER_HOUR
            + parse_int_value(cfg.get(CLOCK_INTERVAL_MINUTES_KEY), default=0, minimum=0) * _SECONDS_PER_MINUTE
            + parse_int_value(cfg.get(CLOCK_INTERVAL_SECONDS_KEY), default=0, minimum=0)
        )
        return _split_total_seconds(total_seconds)

    interval_seconds = cfg.get(CLOCK_INTERVAL_SECONDS_KEY)
    if interval_seconds is None:
        return dict(DEFAULT_CLOCK_INTERVAL_FIELDS)

    return _split_total_seconds(parse_int_value(interval_seconds, default=0, minimum=0))


def parse_clock_interval_seconds(cfg: dict | None) -> int:
    fields = build_clock_interval_fields(cfg)
    days = parse_int_value(fields.get(CLOCK_INTERVAL_DAYS_KEY), default=0, minimum=0)
    hours = parse_int_value(fields.get(CLOCK_INTERVAL_HOURS_KEY), default=0, minimum=0)
    minutes = parse_int_value(fields.get(CLOCK_INTERVAL_MINUTES_KEY), default=0, minimum=0)
    seconds = parse_int_value(fields.get(CLOCK_INTERVAL_SECONDS_KEY), default=0, minimum=0)
    return (
        days * _SECONDS_PER_DAY
        + hours * _SECONDS_PER_HOUR
        + minutes * _SECONDS_PER_MINUTE
        + seconds
    )
