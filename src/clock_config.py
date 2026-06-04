from __future__ import annotations


CLOCK_INTERVAL_DAYS_KEY = "IntervalDays"
CLOCK_INTERVAL_HOURS_KEY = "IntervalHours"
CLOCK_INTERVAL_MINUTES_KEY = "IntervalMinutes"
CLOCK_INTERVAL_SECONDS_KEY = "IntervalSeconds"

LEGACY_CLOCK_INTERVAL_KEYS = ("interval_seconds",)

DEFAULT_CLOCK_INTERVAL_FIELDS = {
    CLOCK_INTERVAL_DAYS_KEY: "0",
    CLOCK_INTERVAL_HOURS_KEY: "0",
    CLOCK_INTERVAL_MINUTES_KEY: "1",
    CLOCK_INTERVAL_SECONDS_KEY: "0",
}

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 60 * _SECONDS_PER_MINUTE
_SECONDS_PER_DAY = 24 * _SECONDS_PER_HOUR


def _parse_non_negative_int(value: object) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = 0
    return max(0, parsed)


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
            _parse_non_negative_int(cfg.get(CLOCK_INTERVAL_DAYS_KEY)) * _SECONDS_PER_DAY
            + _parse_non_negative_int(cfg.get(CLOCK_INTERVAL_HOURS_KEY)) * _SECONDS_PER_HOUR
            + _parse_non_negative_int(cfg.get(CLOCK_INTERVAL_MINUTES_KEY)) * _SECONDS_PER_MINUTE
            + _parse_non_negative_int(cfg.get(CLOCK_INTERVAL_SECONDS_KEY))
        )
        return _split_total_seconds(total_seconds)

    legacy_value = cfg.get(CLOCK_INTERVAL_SECONDS_KEY)
    if legacy_value is None:
        for key in LEGACY_CLOCK_INTERVAL_KEYS:
            value = cfg.get(key)
            if value is not None:
                legacy_value = value
                break
    if legacy_value is None:
        return dict(DEFAULT_CLOCK_INTERVAL_FIELDS)

    return _split_total_seconds(_parse_non_negative_int(legacy_value))


def parse_clock_interval_seconds(cfg: dict | None) -> int:
    fields = build_clock_interval_fields(cfg)
    days = _parse_non_negative_int(fields.get(CLOCK_INTERVAL_DAYS_KEY))
    hours = _parse_non_negative_int(fields.get(CLOCK_INTERVAL_HOURS_KEY))
    minutes = _parse_non_negative_int(fields.get(CLOCK_INTERVAL_MINUTES_KEY))
    seconds = _parse_non_negative_int(fields.get(CLOCK_INTERVAL_SECONDS_KEY))
    return (
        days * _SECONDS_PER_DAY
        + hours * _SECONDS_PER_HOUR
        + minutes * _SECONDS_PER_MINUTE
        + seconds
    )
