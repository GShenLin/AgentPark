from __future__ import annotations

import json
from typing import Any

from src.providers.openai_transport_errors import OpenAIHttpError, OpenAITransportError


class DeepSeekRuntimeError(RuntimeError):
    """Stable DeepSeek provider failure exposed across Chat and Responses paths."""

    def __init__(
        self,
        message: str,
        code: str,
        *,
        status_code: int = 0,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "UNKNOWN")
        self.status_code = max(0, int(status_code or 0))


def deepseek_transport_error(
    endpoint: str,
    error: object,
) -> DeepSeekRuntimeError:
    """Classify one terminal DeepSeek transport or HTTP failure."""

    endpoint_name = str(endpoint or "DeepSeek request")
    if isinstance(error, OpenAIHttpError):
        status = int(error.status_code or 0)
        detail = _provider_error_detail(error.response_body)
        code = _http_error_code(status, detail)
        return DeepSeekRuntimeError(
            f"{endpoint_name}: HTTP {status} - {error.response_body}",
            code,
            status_code=status,
        )
    if isinstance(error, OpenAITransportError):
        return DeepSeekRuntimeError(f"{endpoint_name}: {error}", "TRANSPORT")
    return DeepSeekRuntimeError(f"{endpoint_name}: {error}", "UNKNOWN")


def _http_error_code(status: int, detail: str) -> str:
    if status in {401, 403}:
        return "AUTH"
    if status == 402 or _looks_like_quota_error(detail):
        return "QUOTA"
    if status == 429:
        return "RATE_LIMIT"
    if status == 400:
        return "CONTEXT_WINDOW_EXCEEDED" if _looks_like_context_error(detail) else "INVALID_REQUEST"
    if status >= 500:
        return "SERVER"
    return f"HTTP_{status}"


def _provider_error_detail(response_body: object) -> str:
    text = str(response_body or "")
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return text.lower()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return text.lower()
    return " ".join(str(error.get(key) or "") for key in ("code", "type", "message")).lower()


def _looks_like_quota_error(detail: str) -> bool:
    return any(token in detail for token in ("quota", "balance", "credit", "insufficient"))


def _looks_like_context_error(detail: str) -> bool:
    return any(
        token in detail
        for token in (
            "context length",
            "context_length",
            "context window",
            "context_window",
            "maximum context",
            "too many tokens",
            "max token",
            "max_tokens",
        )
    )


__all__ = ["DeepSeekRuntimeError", "deepseek_transport_error"]
