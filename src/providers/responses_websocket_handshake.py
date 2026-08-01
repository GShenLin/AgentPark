from __future__ import annotations

from typing import Any

from src.providers.openai_transport_errors import OpenAIHttpError
from src.providers.openai_transport_errors import OpenAITransportError


class ResponsesWebSocketUnavailable(RuntimeError):
    """Raised when WebSocket transport cannot be used for this provider session."""


def open_responses_websocket(
    *,
    url: str,
    headers: dict[str, str],
    open_timeout_seconds: float,
) -> Any:
    try:
        from websockets.exceptions import InvalidStatus
        from websockets.sync.client import connect
    except ImportError as exc:
        raise ResponsesWebSocketUnavailable(
            "the websockets package is unavailable"
        ) from exc

    try:
        return connect(
            url,
            additional_headers=headers,
            open_timeout=open_timeout_seconds,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=None,
        )
    except InvalidStatus as exc:
        response = exc.response
        body = response.body
        if isinstance(body, (bytes, bytearray)):
            detail = bytes(body).decode("utf-8", errors="replace")
        else:
            detail = str(body or "")
        raise OpenAIHttpError(
            int(response.status_code),
            detail or str(exc),
            retry_scope="request",
        ) from exc
    except TimeoutError as exc:
        raise OpenAITransportError(
            f"websocket handshake timeout after {open_timeout_seconds}s",
            retry_scope="request",
        ) from exc
    except OSError as exc:
        raise OpenAITransportError(
            f"websocket handshake network failure: {exc}",
            retry_scope="request",
        ) from exc
    except Exception as exc:
        raise OpenAITransportError(
            f"websocket handshake failed: {exc}",
            retry_scope="request",
        ) from exc


__all__ = ["ResponsesWebSocketUnavailable", "open_responses_websocket"]
