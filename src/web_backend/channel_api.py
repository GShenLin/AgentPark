from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from .shared import HTTPException
from src.channels.errors import ChannelConfigError, ChannelError


def channel_http_endpoint(handler: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(handler)
    def endpoint(*args, **kwargs):
        return call_channel_http(handler, *args, **kwargs)

    return endpoint


def call_channel_http(handler: Callable[..., Any], *args, **kwargs) -> Any:
    try:
        return handler(*args, **kwargs)
    except ChannelConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChannelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


__all__ = ["call_channel_http", "channel_http_endpoint"]
