from __future__ import annotations

import datetime as dt
import hashlib
import importlib
from importlib.resources import as_file, files
import re
import threading
from typing import Any, Callable
import zoneinfo

from plugins.tickflow.cache import get_or_fetch
from src.provider_api_key_store import api_key_store_path, load_api_key_store
from src.workspace_settings import get_workspace_root


REQUIRED_TIME_ZONES = ("Asia/Shanghai", "America/New_York", "Asia/Hong_Kong")


def _import_tickflow_api():
    try:
        for key in REQUIRED_TIME_ZONES:
            zoneinfo.ZoneInfo(key)
    except zoneinfo.ZoneInfoNotFoundError:
        original_path = zoneinfo.TZPATH
        bundled_zoneinfo = files("tzdata").joinpath("zoneinfo")
        with as_file(bundled_zoneinfo) as zoneinfo_path:
            zoneinfo.reset_tzpath([str(zoneinfo_path)])
            try:
                for key in REQUIRED_TIME_ZONES:
                    zoneinfo.ZoneInfo(key)
                return importlib.import_module("tickflow")
            finally:
                zoneinfo.reset_tzpath(original_path)
    return importlib.import_module("tickflow")


_tickflow = _import_tickflow_api()
AuthenticationError = _tickflow.AuthenticationError
BadRequestError = _tickflow.BadRequestError
TickFlowConnectionError = _tickflow.ConnectionError
NotFoundError = _tickflow.NotFoundError
TickFlowPermissionError = _tickflow.PermissionError
RateLimitError = _tickflow.RateLimitError
TickFlow = _tickflow.TickFlow
TickFlowError = _tickflow.TickFlowError
TickFlowTimeoutError = _tickflow.TimeoutError


API_KEY_ALIAS = "TickFlow"
SOURCE_NAME = "tickflow"
CLIENT_TIMEOUT_SECONDS = 30.0
TOOL_TIMEOUT_SECONDS = 60.0
MAX_QUOTE_SYMBOLS = 500
MAX_KLINE_SYMBOLS = 200
MAX_KLINE_COUNT = 10000
MAX_KLINE_HISTORY_MILLISECONDS = 365 * 24 * 60 * 60 * 1000
MAX_FINANCIAL_SYMBOLS = 100
MAX_INSTRUMENT_SYMBOLS = 50
MAX_DEPTH_SYMBOLS = 200
PERIODS = ("1m", "5m", "15m", "30m", "60m", "1d", "1w", "1M", "1Q", "1Y")
INTRADAY_PERIODS = ("1m", "5m", "15m", "30m", "60m")
ADJUSTMENTS = ("forward", "forward_additive", "backward", "backward_additive", "none")
FINANCIAL_STATEMENTS = ("income", "balance_sheet", "cash_flow", "metrics", "shares")


class TickFlowToolInputError(ValueError):
    pass


_client_lock = threading.Lock()
_cached_client: TickFlow | None = None
_cached_key_digest = ""


def load_api_key() -> str:
    store_path = api_key_store_path(get_workspace_root())
    store = load_api_key_store(store_path)
    key = store.get(API_KEY_ALIAS)
    if not isinstance(key, str) or not key.strip():
        raise RuntimeError(f"API key alias '{API_KEY_ALIAS}' is missing from {store_path}.")
    return key.strip()


def get_client() -> TickFlow:
    global _cached_client, _cached_key_digest
    api_key = load_api_key()
    key_digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    with _client_lock:
        if _cached_client is not None and _cached_key_digest == key_digest:
            return _cached_client
        if _cached_client is not None:
            _cached_client.close()
        _cached_client = TickFlow(
            api_key=api_key,
            timeout=CLIENT_TIMEOUT_SECONDS,
            max_retries=3,
        )
        _cached_key_digest = key_digest
        return _cached_client


def run_tool(
    operation: str,
    prepare: Callable[[], dict[str, Any]],
    invoke: Callable[[TickFlow, dict[str, Any]], Any],
) -> dict[str, Any]:
    try:
        request = prepare()
        cached = get_or_fetch(
            get_workspace_root(),
            operation,
            request,
            lambda: invoke(get_client(), request),
        )
        return {
            "status": "ok",
            "source": SOURCE_NAME,
            "operation": operation,
            "retrieved_at": cached.fetched_at,
            "served_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "cache": {
                "status": "hit" if cached.cache_hit else "miss",
                "key": cached.cache_key,
                "expires_at": cached.expires_at,
            },
            "request": request,
            "data": cached.data,
        }
    except TickFlowToolInputError as exc:
        return _error(operation, "invalid_arguments", "invalid_arguments", str(exc))
    except AuthenticationError:
        return _error(
            operation,
            "error",
            "authentication",
            f"TickFlow authentication failed for API key alias '{API_KEY_ALIAS}'.",
        )
    except TickFlowPermissionError:
        return _error(operation, "error", "permission_denied", "TickFlow denied access to this data.")
    except RateLimitError:
        return _error(operation, "error", "rate_limited", "TickFlow rate limit exceeded. Retry later.")
    except NotFoundError as exc:
        return _error(operation, "error", "not_found", _safe_error_message(exc, "TickFlow data was not found."))
    except BadRequestError as exc:
        return _error(operation, "error", "bad_request", _safe_error_message(exc, "TickFlow rejected the request."))
    except TickFlowTimeoutError:
        return _error(operation, "error", "timeout", "TickFlow request timed out.")
    except TickFlowConnectionError:
        return _error(operation, "error", "connection", "Could not connect to TickFlow.")
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        return _error(operation, "error", "configuration", _safe_error_message(exc, "TickFlow is not configured."))
    except TickFlowError as exc:
        return _error(operation, "error", "tickflow", _safe_error_message(exc, "TickFlow request failed."))
    except Exception as exc:
        return _error(
            operation,
            "error",
            "unexpected",
            f"Unexpected TickFlow client error: {type(exc).__name__}.",
        )


def _error(operation: str, status: str, error_type: str, message: str) -> dict[str, Any]:
    return {
        "status": status,
        "source": SOURCE_NAME,
        "operation": operation,
        "error_type": error_type,
        "error": message,
    }


def _safe_error_message(exc: Exception, fallback: str) -> str:
    message = str(exc or "").strip() or fallback
    try:
        api_key = load_api_key()
    except Exception:
        api_key = ""
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return re.sub(
        r"(?i)(x-api-key|authorization)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        message,
    )


def string_list(value: Any, label: str, maximum: int) -> list[str]:
    if not isinstance(value, list) or not value:
        raise TickFlowToolInputError(f"{label} must be a non-empty array of strings.")
    if len(value) > maximum:
        raise TickFlowToolInputError(f"{label} accepts at most {maximum} items per call.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or item != item.strip():
            raise TickFlowToolInputError(
                f"Every {label} item must be a non-empty string without surrounding whitespace."
            )
        if item in result:
            raise TickFlowToolInputError(f"{label} must not contain duplicate items.")
        result.append(item)
    return result


def choice(value: Any, label: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise TickFlowToolInputError(f"{label} must be one of: {', '.join(choices)}.")
    return value


def integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise TickFlowToolInputError(f"{label} must be an integer from {minimum} to {maximum}.")
    return value


def _optional_milliseconds(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TickFlowToolInputError(f"{label} must be a non-negative Unix timestamp in milliseconds.")
    return value


def _optional_date(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value != value.strip():
        raise TickFlowToolInputError(f"{label} must use YYYY-MM-DD without surrounding whitespace.")
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise TickFlowToolInputError(f"{label} must be a valid YYYY-MM-DD date.") from exc
    return value


def prepare_klines(symbols, period, count, adjust, start_time, end_time):
    request = {
        "symbols": string_list(symbols, "symbols", MAX_KLINE_SYMBOLS),
        "period": choice(period, "period", PERIODS),
        "count": integer(count, "count", 1, MAX_KLINE_COUNT),
        "adjust": choice(adjust, "adjust", ADJUSTMENTS),
        "start_time": _optional_milliseconds(start_time, "start_time"),
        "end_time": _optional_milliseconds(end_time, "end_time"),
    }
    if request["start_time"] is not None and request["end_time"] is not None:
        if request["start_time"] > request["end_time"]:
            raise TickFlowToolInputError("start_time must not be later than end_time.")
        if (
            request["period"] in INTRADAY_PERIODS
            and request["end_time"] - request["start_time"] > MAX_KLINE_HISTORY_MILLISECONDS
        ):
            raise TickFlowToolInputError("Minute K-line history range must not exceed 365 days.")
    return request


def invoke_klines(client: TickFlow, request: dict[str, Any]):
    symbols = request["symbols"]
    if len(symbols) == 1:
        symbol = symbols[0]
        return {
            symbol: client.klines.get(
                symbol,
                period=request["period"],
                count=request["count"],
                adjust=request["adjust"],
                start_time=request["start_time"],
                end_time=request["end_time"],
                as_dataframe=False,
            )
        }
    return client.klines.batch(
        symbols,
        period=request["period"],
        count=request["count"],
        adjust=request["adjust"],
        start_time=request["start_time"],
        end_time=request["end_time"],
        as_dataframe=False,
        show_progress=False,
        max_workers=min(5, len(symbols)),
        batch_size=MAX_KLINE_SYMBOLS,
    )


def invoke_intraday(client: TickFlow, request: dict[str, Any]):
    symbols = request["symbols"]
    if len(symbols) == 1:
        symbol = symbols[0]
        return {
            symbol: client.klines.intraday(
                symbol,
                period=request["period"],
                count=request["count"],
                as_dataframe=False,
            )
        }
    return client.klines.intraday_batch(
        symbols,
        period=request["period"],
        count=request["count"],
        as_dataframe=False,
        show_progress=False,
        max_workers=min(5, len(symbols)),
        batch_size=MAX_KLINE_SYMBOLS,
    )


def invoke_depth(client: TickFlow, request: dict[str, Any]):
    symbols = request["symbols"]
    if len(symbols) == 1:
        symbol = symbols[0]
        return {symbol: client.depth.get(symbol)}
    return client.depth.batch(
        symbols,
        batch_size=MAX_DEPTH_SYMBOLS,
        max_workers=min(5, len(symbols)),
        show_progress=False,
    )


def prepare_financials(symbols, statement, start_date, end_date, latest):
    if not isinstance(latest, bool):
        raise TickFlowToolInputError("latest must be a boolean.")
    request = {
        "symbols": string_list(symbols, "symbols", MAX_FINANCIAL_SYMBOLS),
        "statement": choice(statement, "statement", FINANCIAL_STATEMENTS),
        "start_date": _optional_date(start_date, "start_date"),
        "end_date": _optional_date(end_date, "end_date"),
        "latest": latest,
    }
    if request["start_date"] and request["end_date"] and request["start_date"] > request["end_date"]:
        raise TickFlowToolInputError("start_date must not be later than end_date.")
    if not latest and not request["start_date"] and not request["end_date"]:
        raise TickFlowToolInputError("latest=false requires a bounded start_date or end_date.")
    return request


def invoke_financials(client: TickFlow, request: dict[str, Any]):
    method = getattr(client.financials, request["statement"])
    return method(
        request["symbols"],
        start_date=request["start_date"],
        end_date=request["end_date"],
        latest=request["latest"],
        as_dataframe=False,
        show_progress=False,
        max_workers=min(5, len(request["symbols"])),
    )


def universe_detail(client: TickFlow, request: dict[str, Any]):
    detail = dict(client.universes.get(request["universe_id"]))
    symbols = list(detail.get("symbols") or [])
    detail["symbols"] = symbols[: request["symbol_limit"]]
    detail["symbols_total"] = len(symbols)
    detail["symbols_truncated"] = len(symbols) > request["symbol_limit"]
    return detail
