from __future__ import annotations

from dataclasses import dataclass
import math
import random
import re
from typing import Mapping

from src.providers.provider_errors import ProviderConfigError


DEFAULT_REQUEST_MAX_RETRIES = 4
DEFAULT_STREAM_MAX_RETRIES = 5
DEFAULT_OVERLOAD_MAX_RETRIES = 5
DEFAULT_RETRY_DELAY_SECONDS = 1.0
DEFAULT_RETRY_MAX_DELAY_SECONDS = 30.0
DEFAULT_RETRY_JITTER_RATIO = 0.1
DEFAULT_REQUEST_TIMEOUT_MS = 60_000
DEFAULT_STREAM_IDLE_TIMEOUT_MS = 300_000
DEFAULT_WEBSOCKET_CONNECT_TIMEOUT_MS = 15_000
MAX_RETRIES_LIMIT = 100

_RETRY_AFTER_RE = re.compile(
    r"(?:please\s+)?try\s+again\s+in\s+"
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>ms|milliseconds?|s|sec(?:ond)?s?)\b",
    re.IGNORECASE,
)
_OVERLOAD_CODES = frozenset({"server_is_overloaded", "slow_down"})
_RECOVERABLE_STATE_CODES = frozenset(
    {
        "previous_response_not_found",
        "websocket_connection_limit_reached",
    }
)
_FATAL_RESPONSES_FAILURE_CODES = frozenset(
    {
        "bio_policy",
        "context_length_exceeded",
        "cyber_policy",
        "insufficient_quota",
        "invalid_prompt",
        "usage_not_included",
    }
)
_TRANSIENT_CODES = frozenset(
    {
        "internal_server_error",
        "server_error",
        "service_unavailable",
        "temporarily_unavailable",
    }
)


@dataclass(frozen=True)
class OpenAIRetryPolicy:
    request_max_retries: int
    stream_max_retries: int
    overload_max_retries: int
    base_delay_seconds: float
    max_delay_seconds: float
    jitter_ratio: float

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "OpenAIRetryPolicy":
        shared_max_retries = (
            _integer(
                config,
                "maxRetries",
                default=DEFAULT_STREAM_MAX_RETRIES,
                minimum=0,
                maximum=MAX_RETRIES_LIMIT,
            )
            if "maxRetries" in config
            else None
        )
        request_max_retries = _integer(
            config,
            "requestMaxRetries",
            default=(
                shared_max_retries
                if shared_max_retries is not None
                else DEFAULT_REQUEST_MAX_RETRIES
            ),
            minimum=0,
            maximum=MAX_RETRIES_LIMIT,
        )
        stream_max_retries = _integer(
            config,
            "streamMaxRetries",
            default=(
                shared_max_retries
                if shared_max_retries is not None
                else DEFAULT_STREAM_MAX_RETRIES
            ),
            minimum=0,
            maximum=MAX_RETRIES_LIMIT,
        )
        overload_max_retries = _integer(
            config,
            "overloadMaxRetries",
            default=max(DEFAULT_OVERLOAD_MAX_RETRIES, stream_max_retries),
            minimum=0,
            maximum=MAX_RETRIES_LIMIT,
        )
        return cls(
            request_max_retries=request_max_retries,
            stream_max_retries=stream_max_retries,
            overload_max_retries=overload_max_retries,
            base_delay_seconds=_number(
                config,
                "retryDelaySec",
                default=DEFAULT_RETRY_DELAY_SECONDS,
                minimum=0.0,
            ),
            max_delay_seconds=_number(
                config,
                "retryMaxDelaySec",
                default=DEFAULT_RETRY_MAX_DELAY_SECONDS,
                minimum=0.0,
            ),
            jitter_ratio=_number(
                config,
                "retryJitterRatio",
                default=DEFAULT_RETRY_JITTER_RATIO,
                minimum=0.0,
                maximum=0.5,
            ),
        )

    def retry_limit(self, *, scope: str, provider_code: str = "") -> int:
        if normalize_provider_code(provider_code) in _OVERLOAD_CODES:
            return self.overload_max_retries
        if scope == "request":
            return self.request_max_retries
        if scope == "stream":
            return self.stream_max_retries
        raise ValueError("retry scope must be 'request' or 'stream'")

    def delay_seconds(
        self,
        *,
        attempt: int,
        error_text: str,
        jitter: float | None = None,
    ) -> float:
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt <= 0:
            raise ValueError("retry attempt must be a positive integer")
        requested = parse_retry_after_seconds(error_text)
        if requested is not None:
            return min(requested, self.max_delay_seconds)
        exponential = self.base_delay_seconds * (2 ** (attempt - 1))
        capped = min(exponential, self.max_delay_seconds)
        if capped == 0 or self.jitter_ratio == 0:
            return capped
        factor = (
            random.uniform(1.0 - self.jitter_ratio, 1.0 + self.jitter_ratio)
            if jitter is None
            else _jitter_factor(jitter, self.jitter_ratio)
        )
        return min(capped * factor, self.max_delay_seconds)


@dataclass(frozen=True)
class OpenAIRetryDecision:
    scope: str
    category: str
    attempt: int
    max_retries: int


class OpenAIRetryState:
    def __init__(self, policy: OpenAIRetryPolicy, *, scope: str):
        if scope not in {"request", "stream"}:
            raise ValueError("retry scope must be 'request' or 'stream'")
        self._policy = policy
        self._scope = scope
        self._attempts = {"general": 0, "overload": 0}

    def next_retry(self, *, provider_code: str = "") -> OpenAIRetryDecision | None:
        category = (
            "overload"
            if is_server_overloaded_code(provider_code)
            else "general"
        )
        max_retries = self._policy.retry_limit(
            scope=self._scope,
            provider_code=provider_code,
        )
        attempt = self._attempts[category] + 1
        if attempt > max_retries:
            return None
        self._attempts[category] = attempt
        return OpenAIRetryDecision(
            scope=self._scope,
            category=category,
            attempt=attempt,
            max_retries=max_retries,
        )


@dataclass(frozen=True)
class OpenAITransportTimeouts:
    request_seconds: float
    stream_idle_seconds: float
    websocket_connect_seconds: float

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "OpenAITransportTimeouts":
        return cls(
            request_seconds=_timeout_seconds(
                config,
                "timeoutMs",
                default=DEFAULT_REQUEST_TIMEOUT_MS,
            ),
            stream_idle_seconds=_timeout_seconds(
                config,
                "streamIdleTimeoutMs",
                default=DEFAULT_STREAM_IDLE_TIMEOUT_MS,
            ),
            websocket_connect_seconds=_timeout_seconds(
                config,
                "websocketConnectTimeoutMs",
                default=DEFAULT_WEBSOCKET_CONNECT_TIMEOUT_MS,
            ),
        )


def normalize_provider_code(value: object) -> str:
    return str(value or "").strip().lower()


def is_server_overloaded_code(value: object) -> bool:
    return normalize_provider_code(value) in _OVERLOAD_CODES


def is_retryable_provider_code(value: object) -> bool:
    code = normalize_provider_code(value)
    return (
        code in _OVERLOAD_CODES
        or code in _RECOVERABLE_STATE_CODES
        or code in _TRANSIENT_CODES
    )


def is_fatal_responses_failure_code(value: object) -> bool:
    return normalize_provider_code(value) in _FATAL_RESPONSES_FAILURE_CODES


def parse_retry_after_seconds(error_text: object) -> float | None:
    match = _RETRY_AFTER_RE.search(str(error_text or ""))
    if match is None:
        return None
    value = float(match.group("value"))
    unit = match.group("unit").lower()
    return value / 1000.0 if unit.startswith("ms") or unit.startswith("millisecond") else value


def _integer(
    config: Mapping[str, object],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if key not in config:
        return default
    value = config[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProviderConfigError(f"{key} must be an integer")
    if value < minimum or value > maximum:
        raise ProviderConfigError(f"{key} must be between {minimum} and {maximum}")
    return value


def _number(
    config: Mapping[str, object],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float | None = None,
) -> float:
    if key not in config:
        return default
    value = config[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderConfigError(f"{key} must be a number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ProviderConfigError(f"{key} must be finite")
    if parsed < minimum or (maximum is not None and parsed > maximum):
        if maximum is None:
            raise ProviderConfigError(f"{key} must be at least {minimum}")
        raise ProviderConfigError(f"{key} must be between {minimum} and {maximum}")
    return parsed


def _timeout_seconds(
    config: Mapping[str, object],
    key: str,
    *,
    default: int,
) -> float:
    milliseconds = _integer(
        config,
        key,
        default=default,
        minimum=1,
        maximum=2_147_483_647,
    )
    return milliseconds / 1000.0


def _jitter_factor(value: float, ratio: float) -> float:
    parsed = float(value)
    lower = 1.0 - ratio
    upper = 1.0 + ratio
    if parsed < lower or parsed > upper:
        raise ValueError(f"jitter factor must be between {lower} and {upper}")
    return parsed
