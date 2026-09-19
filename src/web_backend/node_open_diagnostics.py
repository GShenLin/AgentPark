"""Temporary node-open measurements; never record message or command content."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .runtime_paths import _get_runtime_root

Metric = Annotated[float, Field(allow_inf_nan=False)]


class BrowserMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal[
        "selection", "selection_watch", "board_selection_flush", "board_focus", "memory_shown", "request_start", "response_headers",
        "response_json", "request_failed", "memory_applied", "live_applied",
        "vue_flush", "frame_after_update", "scroll_layout", "longtask",
        "long_animation_frame", "capture_end",
    ]
    at_ms: Metric
    metrics: dict[Annotated[str, Field(pattern=r"^[a-z_]{1,64}$")], Metric] = Field(max_length=24)
    endpoint: str = Field(default="", max_length=512, pattern=r"^(?:/api/[^?\r\n]*)?$")
    request_id: str = Field(default="", max_length=80, pattern=r"^[a-zA-Z0-9-]*$")


class BrowserTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trace_id: UUID
    graph_id: str = Field(max_length=200)
    node_id: str = Field(max_length=200)
    started_at: str = Field(max_length=40)
    events: list[BrowserMeasurement] = Field(max_length=500)


_logger_lock = threading.Lock()
_logger: logging.Logger | None = None
_request_trace: ContextVar[dict | None] = ContextVar("node_open_trace", default=None)


def write_measurement(record: dict) -> None:
    global _logger
    # File I/O happens after response transmission / outside measured spans.
    with _logger_lock:
        if _logger is None:
            path = os.path.join(_get_runtime_root(), "logs", "node-open-performance.jsonl")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            _logger = logging.Logger("node-open-performance", logging.INFO)
            _logger.addHandler(handler)
        _logger.info(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(), **record}, ensure_ascii=False))


def receive_browser_trace(node_id: str, payload: BrowserTrace, graph_id: str = "") -> dict:
    from fastapi import HTTPException

    if payload.node_id != node_id or payload.graph_id != graph_id:
        raise HTTPException(status_code=400, detail="trace target does not match route")
    write_measurement({"source": "browser", **payload.model_dump(mode="json")})
    return {"ok": True}


def checkpoint(stage: str, **metrics: int | float) -> None:
    trace = _request_trace.get()
    if trace is None:
        return
    now = time.perf_counter()
    trace["phases"].append({"stage": stage, "elapsed_ms": round((now - trace["last"]) * 1000, 3), **metrics})
    trace["last"] = now


class NodeOpenDiagnosticsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        trace_id = headers.get("x-node-open-trace", "")
        if not re.fullmatch(r"[a-fA-F0-9-]{36}", trace_id):
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        trace = {"last": started, "phases": []}
        token = _request_trace.set(trace)
        status, body_bytes, headers_ms = None, 0, None
        failure = None

        async def measured_send(message: Message) -> None:
            nonlocal status, body_bytes, headers_ms
            if message["type"] == "http.response.start":
                status = message["status"]
                headers_ms = (time.perf_counter() - started) * 1000
                checkpoint("response_ready")
            elif message["type"] == "http.response.body":
                body_bytes += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
        except Exception as exc:
            failure = type(exc).__name__
            raise
        finally:
            total_ms = (time.perf_counter() - started) * 1000
            _request_trace.reset(token)
            record = {
                "source": "server", "trace_id": trace_id,
                "request_id": headers.get("x-node-open-request", "")[:80],
                "endpoint": scope["path"], "status": status, "error_type": failure,
                "headers_ms": headers_ms, "total_ms": total_ms,
                "body_bytes": body_bytes, "phases": trace["phases"],
            }
            try:
                write_measurement(record)
            except OSError as exc:
                # A diagnostic disk failure must not replace the API result/error.
                print(f"[NodeOpenPerformance] failed to save server trace: {exc}", file=sys.stderr)
