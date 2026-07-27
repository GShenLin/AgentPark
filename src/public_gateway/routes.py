from __future__ import annotations

import json
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

from .service import PublicGatewayService


def register_public_gateway_routes(app: FastAPI, service: PublicGatewayService) -> None:
    @app.get("/v1/models")
    def list_models(request: Request):
        unauthorized = _authorization_error(request, service, protocol="responses")
        return unauthorized or service.models()

    @app.post("/v1/responses")
    def responses(request: Request, payload: dict[str, Any]):
        return _dispatch(request, service, "responses", payload)

    @app.post("/v1/chat/completions")
    def chat_completions(request: Request, payload: dict[str, Any]):
        return _dispatch(request, service, "chat_completions", payload)

    @app.post("/v1/messages")
    def messages(request: Request, payload: dict[str, Any]):
        return _dispatch(request, service, "messages", payload)


def _dispatch(
    request: Request,
    service: PublicGatewayService,
    protocol: str,
    payload: dict[str, Any],
):
    unauthorized = _authorization_error(request, service, protocol=protocol)
    if unauthorized is not None:
        return unauthorized
    try:
        result = service.dispatch(protocol, payload)
        headers = {"x-request-id": f"req_{uuid.uuid4().hex}"}
        if result.stream is not None:
            return StreamingResponse(
                _guard_stream(protocol, result.stream),
                status_code=result.status,
                media_type=result.content_type,
                headers={**headers, "Cache-Control": "no-cache"},
            )
        return JSONResponse(
            result.json_body,
            status_code=result.status,
            media_type=result.content_type,
            headers=headers,
        )
    except UpstreamHttpError as exc:
        return Response(
            content=exc.body,
            status_code=exc.status,
            media_type=exc.headers.get("content-type", "application/json"),
        )
    except KeyError as exc:
        return _error(protocol, 404, _exception_message(exc))
    except ValueError as exc:
        return _error(protocol, 400, str(exc))
    except RuntimeError as exc:
        return _error(protocol, 503, str(exc))
    except Exception as exc:
        return _error(protocol, 500, f"{type(exc).__name__}: {exc}")


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


def _guard_stream(protocol: str, stream: Iterable[bytes]) -> Iterable[bytes]:
    try:
        yield from stream
    except Exception as exc:
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
