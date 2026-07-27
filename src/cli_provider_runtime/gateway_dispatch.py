from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from src.provider_auth.credentials import resolve_provider_request_credentials

from .chat_conversion import chat_request_to_canonical
from .chat_wire import canonical_result_to_chat
from .chat_wire import responses_sse_to_chat
from .http_transport import UpstreamHttpError
from .http_transport import open_json_request
from .http_transport import read_json_response
from .http_transport import resolve_upstream_request_policy
from .messages_conversion import messages_request_to_canonical
from .messages_wire import canonical_result_to_message
from .messages_wire import responses_sse_to_messages
from .provider_adapter import create_chat_adapter
from .provider_adapter import provider_protocol
from .responses_conversion import canonical_result_to_response
from .responses_conversion import responses_request_to_canonical
from .responses_passthrough import ResponsesPassthrough
from .responses_stream import collect_responses_stream


@dataclass(frozen=True)
class GatewayDispatchResult:
    status: int
    content_type: str
    json_body: dict[str, Any] | None = None
    stream: Iterable[bytes] | None = None

    def __post_init__(self) -> None:
        if (self.json_body is None) == (self.stream is None):
            raise ValueError("Gateway dispatch result requires exactly one body representation.")


def dispatch_responses(config: dict[str, Any], payload: dict[str, Any]) -> GatewayDispatchResult:
    model, request_payload = _provider_request(config, payload)
    if provider_protocol(config) == "responses":
        passthrough = ResponsesPassthrough(config)
        prepared = passthrough.prepare_request(request_payload)
        requested_stream = bool(prepared.payload.get("stream"))
        requires_stream = str(config.get("authMode") or "").strip().lower() == "codex"
        upstream_payload = dict(prepared.payload)
        if requires_stream:
            upstream_payload["stream"] = True
        response = _open_responses(config, upstream_payload, force_refresh=False)
        content_type = response.headers.get("content-type", "application/json")
        transformed = passthrough.transform_stream(response, prepared.tools_by_wire_name)
        if requested_stream:
            return GatewayDispatchResult(
                status=response.status,
                content_type=content_type,
                stream=transformed,
            )
        if requires_stream:
            value = collect_responses_stream(transformed)
            return GatewayDispatchResult(
                status=200,
                content_type="application/json",
                json_body=value,
            )
        value = passthrough.transform_response(
            read_json_response(response),
            prepared.tools_by_wire_name,
        )
        return GatewayDispatchResult(status=200, content_type="application/json", json_body=value)

    request = responses_request_to_canonical(request_payload, model=model)
    adapter = create_chat_adapter(config)
    if request.stream:
        return GatewayDispatchResult(
            status=200,
            content_type="text/event-stream",
            stream=adapter.stream(request, response_id=f"resp_agentpark_{uuid.uuid4().hex}"),
        )
    result = adapter.complete(request)
    return GatewayDispatchResult(
        status=200,
        content_type="application/json",
        json_body=canonical_result_to_response(result, model=model),
    )


def dispatch_chat_completions(config: dict[str, Any], payload: dict[str, Any]) -> GatewayDispatchResult:
    model, request_payload = _provider_request(config, payload)
    request = chat_request_to_canonical(request_payload, model=model)
    adapter = create_chat_adapter(config)
    if request.stream:
        return GatewayDispatchResult(
            status=200,
            content_type="text/event-stream",
            stream=responses_sse_to_chat(adapter.stream(request), model=model),
        )
    result = adapter.complete(request)
    return GatewayDispatchResult(
        status=200,
        content_type="application/json",
        json_body=canonical_result_to_chat(result, model=model),
    )


def dispatch_messages(config: dict[str, Any], payload: dict[str, Any]) -> GatewayDispatchResult:
    model, request_payload = _provider_request(config, payload)
    request = messages_request_to_canonical(request_payload, model=model)
    adapter = create_chat_adapter(config)
    if request.stream:
        return GatewayDispatchResult(
            status=200,
            content_type="text/event-stream",
            stream=responses_sse_to_messages(adapter.stream(request), model=model),
        )
    result = adapter.complete(request)
    return GatewayDispatchResult(
        status=200,
        content_type="application/json",
        json_body=canonical_result_to_message(result, model=model),
    )


def _provider_request(
    config: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Gateway request body must be a JSON object.")
    model = str(config.get("model") or "").strip()
    if not model:
        raise ValueError("Gateway Provider has no model.")
    request_payload = dict(payload)
    request_payload["model"] = model
    return model, request_payload


def _open_responses(
    config: dict[str, Any],
    payload: dict[str, Any],
    *,
    force_refresh: bool,
):
    credentials = resolve_provider_request_credentials(config, force_refresh=force_refresh)
    base_url = credentials.base_url.rstrip("/")
    url = base_url if base_url.endswith("/responses") else f"{base_url}/responses"
    try:
        return open_json_request(
            url=url,
            headers=credentials.headers,
            payload=payload,
            policy=resolve_upstream_request_policy(config),
            stream=bool(payload.get("stream")),
        )
    except UpstreamHttpError as exc:
        auth_mode = str(config.get("authMode") or "").lower()
        if exc.status == 401 and auth_mode in {"codex", "oauth"} and not force_refresh:
            return _open_responses(config, payload, force_refresh=True)
        raise


__all__ = [
    "GatewayDispatchResult",
    "dispatch_chat_completions",
    "dispatch_messages",
    "dispatch_responses",
]
