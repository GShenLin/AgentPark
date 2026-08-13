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
from .service import PublicGatewayService


def register_public_gateway_routes(app: FastAPI, service: PublicGatewayService) -> None:
    access_log = PublicGatewayAccessLog(service.workspace_root)

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
        return _dispatch(request, service, "responses", payload, access_log)

    @app.post("/v1/chat/completions")
    def chat_completions(request: Request, payload: dict[str, Any]):
        return _dispatch(request, service, "chat_completions", payload, access_log)

    @app.post("/v1/messages")
    def messages(request: Request, payload: dict[str, Any]):
        return _dispatch(request, service, "messages", payload, access_log)


def _dispatch(
    request: Request,
    service: PublicGatewayService,
    protocol: str,
    payload: dict[str, Any],
    access_log: PublicGatewayAccessLog,
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
                ),
                status_code=result.status,
                media_type=result.content_type,
                headers={**headers, "Cache-Control": "no-cache"},
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
) -> Iterable[bytes]:
    try:
        yield from stream
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
        access_log.record(
            "stream_completed",
            **request_fields,
            status=200,
            durationMs=_duration_ms(started_at),
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


def _request_fields(request: Request, request_id: str) -> dict[str, Any]:
    client_ip = request.client.host if request.client else ""
    return {
        "requestId": request_id,
        "clientIp": client_ip,
        "method": request.method,
        "path": request.url.path,
        "userAgent": request.headers.get("user-agent", "")[:200],
        "authorizationPresent": bool(
            request.headers.get("authorization") or request.headers.get("x-api-key")
        ),
    }


def _request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


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
