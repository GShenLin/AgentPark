from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from fastapi.responses import StreamingResponse

from src.cli_provider_runtime.http_transport import UpstreamHttpError
from src.cli_provider_runtime.responses_conversion import stream_failed

from .access_log import PublicGatewayAccessLog
from .access_log import safe_error_message
from .access_log import request_fields as _request_fields, new_request_id as _request_id
from .service import PublicGatewayService
from .usage_stats import GatewayUsageAccumulator
from .usage_stats import PublicGatewayUsageStore
from .request_diagnostics import register_request_diagnostics


def register_public_gateway_routes(app: FastAPI, service: PublicGatewayService) -> None:
    access_log = PublicGatewayAccessLog(service.workspace_root)
    register_request_diagnostics(app, access_log)
    usage_store = PublicGatewayUsageStore(service.workspace_root)

    @app.get("/v1/models")
    def list_models(request: Request):
        request_id = _request_id()
        started_at = time.perf_counter()
        unauthorized = _authorization_error(request, service, protocol="responses")
        if unauthorized is not None:
            access_log.record(
                "request_rejected",
                **_request_fields(request, request_id),
                status=401,
                reason="invalid_endpoint_key",
                durationMs=_duration_ms(started_at),
            )
            unauthorized.headers["x-request-id"] = request_id
            return unauthorized
        response = service.models()
        access_log.record(
            "request_completed",
            **_request_fields(request, request_id),
            status=200,
            modelCount=len(response.get("data", [])),
            durationMs=_duration_ms(started_at),
        )
        return JSONResponse(response, headers={"x-request-id": request_id})

    @app.post("/v1/responses")
    def responses(request: Request, payload: dict[str, Any]):
        return _dispatch(request, service, "responses", payload, access_log, usage_store)

    @app.post("/v1/chat/completions")
    def chat_completions(request: Request, payload: dict[str, Any]):
        return _dispatch(request, service, "chat_completions", payload, access_log, usage_store)

    @app.post("/v1/messages")
    def messages(request: Request, payload: dict[str, Any]):
        return _dispatch(request, service, "messages", payload, access_log, usage_store)

    @app.post("/v1/images/generations")
    def images_generations(request: Request, payload: dict[str, Any]):
        return _dispatch(request, service, "images_generations", payload, access_log, usage_store)

    @app.post("/v1/images/edits")
    def images_edits(request: Request, payload: dict[str, Any]):
        return _dispatch(request, service, "images_edits", payload, access_log, usage_store)


def _dispatch(
    request: Request,
    service: PublicGatewayService,
    protocol: str,
    payload: dict[str, Any],
    access_log: PublicGatewayAccessLog,
    usage_store: PublicGatewayUsageStore,
):
    request_id = _request_id()
    started_at = time.perf_counter()
    public_model = str(payload.get("model") or "").strip()
    request_fields = {
        **_request_fields(request, request_id),
        "protocol": protocol,
        "publicModel": public_model or None,
        "stream": bool(payload.get("stream")),
    }
    unauthorized = _authorization_error(request, service, protocol=protocol)
    if unauthorized is not None:
        access_log.record(
            "request_rejected",
            **request_fields,
            status=401,
            reason="invalid_endpoint_key",
            durationMs=_duration_ms(started_at),
        )
        unauthorized.headers["x-request-id"] = request_id
        return unauthorized
    try:
        route = service.route_metadata(protocol, public_model)
        request_fields.update(route)
        access_log.record("request_routed", **request_fields)
        result = service.dispatch(protocol, payload)
        usage_accumulator = GatewayUsageAccumulator(protocol)
        headers = {"x-request-id": request_id}
        if result.stream is not None:
            access_log.record(
                "stream_started",
                **request_fields,
                status=result.status,
                contentType=result.content_type,
                durationMs=_duration_ms(started_at),
            )
            return StreamingResponse(
                _guard_stream(
                    protocol,
                    result.stream,
                    access_log=access_log,
                    request_fields=request_fields,
                    started_at=started_at,
                    status=result.status,
                    usage_accumulator=usage_accumulator,
                    usage_store=usage_store,
                ),
                status_code=result.status,
                media_type=result.content_type,
                headers={**headers, "Cache-Control": "no-cache"},
            )
        usage_accumulator.consume_json(result.json_body)
        if 200 <= result.status < 300:
            _record_usage(
                usage_store,
                usage_accumulator,
                access_log=access_log,
                request_fields=request_fields,
                protocol=protocol,
            )
        access_log.record(
            "request_completed",
            **request_fields,
            status=result.status,
            contentType=result.content_type,
            durationMs=_duration_ms(started_at),
        )
        return JSONResponse(
            result.json_body,
            status_code=result.status,
            media_type=result.content_type,
            headers=headers,
        )
    except UpstreamHttpError as exc:
        access_log.record(
            "request_failed",
            **request_fields,
            status=exc.status,
            errorType=type(exc).__name__,
            error=safe_error_message(exc),
            durationMs=_duration_ms(started_at),
        )
        return Response(
            content=exc.body,
            status_code=exc.status,
            media_type=exc.headers.get("content-type", "application/json"),
            headers={"x-request-id": request_id},
        )
    except KeyError as exc:
        return _logged_error(access_log, request_fields, started_at, protocol, 404, exc)
    except ValueError as exc:
        return _logged_error(access_log, request_fields, started_at, protocol, 400, exc)
    except RuntimeError as exc:
        return _logged_error(access_log, request_fields, started_at, protocol, 503, exc)
    except Exception as exc:
        return _logged_error(access_log, request_fields, started_at, protocol, 500, exc)


def _authorization_error(
    request: Request,
    service: PublicGatewayService,
    *,
    protocol: str,
) -> Response | None:
    if service.authorize(
        request.headers.get("authorization", ""),
        request.headers.get("x-api-key", ""),
    ):
        return None
    return _error(protocol, 401, "Invalid or missing AgentPark Endpoint Key.")


def _guard_stream(
    protocol: str,
    stream: Iterable[bytes],
    *,
    access_log: PublicGatewayAccessLog,
    request_fields: dict[str, Any],
    started_at: float,
    status: int,
    usage_accumulator: GatewayUsageAccumulator,
    usage_store: PublicGatewayUsageStore,
) -> Iterable[bytes]:
    try:
        for chunk in stream:
            usage_accumulator.consume_stream_chunk(chunk)
            yield chunk
    except Exception as exc:
        access_log.record(
            "stream_failed",
            **request_fields,
            status=200,
            errorType=type(exc).__name__,
            error=safe_error_message(exc),
            durationMs=_duration_ms(started_at),
        )
        message = f"{type(exc).__name__}: {exc}"
        if protocol == "responses":
            yield stream_failed(f"resp_agentpark_{uuid.uuid4().hex}", message)
            return
        if protocol == "messages":
            payload = {
                "type": "error",
                "error": {"type": "agentpark_gateway_error", "message": message},
            }
            yield _sse("error", payload)
            return
        payload = {
            "error": {
                "message": message,
                "type": "agentpark_gateway_error",
            }
        }
        yield f"data: {_json(payload)}\n\ndata: [DONE]\n\n".encode("utf-8")
    else:
        if 200 <= status < 300:
            _record_usage(
                usage_store,
                usage_accumulator,
                access_log=access_log,
                request_fields=request_fields,
                protocol=protocol,
            )
        access_log.record(
            "stream_completed",
            **request_fields,
            status=200,
            durationMs=_duration_ms(started_at),
        )


def _record_usage(
    usage_store: PublicGatewayUsageStore,
    accumulator: GatewayUsageAccumulator,
    *,
    access_log: PublicGatewayAccessLog,
    request_fields: dict[str, Any],
    protocol: str,
) -> None:
    try:
        usage_store.record_completed(
            request_id=str(request_fields["requestId"]),
            client_ip=str(request_fields.get("clientIp") or ""),
            model_id=str(request_fields.get("publicModel") or ""),
            protocol=protocol,
            usage=accumulator.usage(),
        )
    except Exception as exc:
        access_log.record(
            "usage_record_failed",
            **request_fields,
            errorType=type(exc).__name__,
            error=safe_error_message(exc),
        )


def _logged_error(
    access_log: PublicGatewayAccessLog,
    request_fields: dict[str, Any],
    started_at: float,
    protocol: str,
    status: int,
    exc: Exception,
) -> JSONResponse:
    message = _exception_message(exc)
    access_log.record(
        "request_failed",
        **request_fields,
        status=status,
        errorType=type(exc).__name__,
        error=safe_error_message(exc),
        durationMs=_duration_ms(started_at),
    )
    response = _error(protocol, status, message)
    response.headers["x-request-id"] = str(request_fields["requestId"])
    return response


def _duration_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def _error(protocol: str, status: int, message: str) -> JSONResponse:
    if protocol == "messages":
        payload = {
            "type": "error",
            "error": {"type": "agentpark_gateway_error", "message": str(message)},
        }
    else:
        payload = {
            "error": {
                "message": str(message),
                "type": "agentpark_gateway_error",
                "code": status,
            }
        }
    return JSONResponse(payload, status_code=status)


def _exception_message(exc: Exception) -> str:
    if exc.args:
        return str(exc.args[0])
    return str(exc)


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {_json(payload)}\n\n".encode("utf-8")


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


__all__ = ["register_public_gateway_routes"]
