from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from typing import Any

from src.provider_auth.credentials import resolve_provider_request_credentials

from .contracts import CanonicalRequest
from .contracts import CanonicalResult
from .contracts import CanonicalToolCall
from .contracts import CodexProtocolError
from .http_transport import open_json_request
from .http_transport import read_json_response
from .http_transport import resolve_upstream_request_policy
from .responses_payload import canonical_request_to_responses
from .responses_passthrough import ResponsesPassthrough
from .responses_stream import collect_responses_stream


class ResponsesConversationAdapter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)

    def complete(self, request: CanonicalRequest) -> CanonicalResult:
        payload = canonical_request_to_responses(request)
        requires_stream = str(self.config.get("authMode") or "").strip().lower() == "codex"
        payload["stream"] = requires_stream
        passthrough = ResponsesPassthrough(self.config)
        prepared = passthrough.prepare_request(payload)
        response = self._open(prepared.payload, stream=requires_stream)
        if requires_stream:
            value = collect_responses_stream(
                passthrough.transform_stream(
                    response, prepared.tools_by_wire_name, seed_tools=prepared.seed_tools
                )
            )
        else:
            value = passthrough.transform_response(
                read_json_response(response),
                prepared.tools_by_wire_name,
                seed_tools=prepared.seed_tools,
            )
        return _result(value)

    def stream(self, request: CanonicalRequest, *, response_id: str = "") -> Iterable[bytes]:
        payload = canonical_request_to_responses(request)
        payload["stream"] = True
        passthrough = ResponsesPassthrough(self.config)
        prepared = passthrough.prepare_request(payload)
        response = self._open(prepared.payload, stream=True)
        yield from passthrough.transform_stream(
            response, prepared.tools_by_wire_name, seed_tools=prepared.seed_tools
        )

    def _open(self, payload: dict[str, Any], *, stream: bool):
        credentials = resolve_provider_request_credentials(self.config)
        base_url = credentials.base_url.rstrip("/")
        url = base_url if base_url.endswith("/responses") else f"{base_url}/responses"
        return open_json_request(
            url=url,
            headers=credentials.headers,
            payload=payload,
            policy=resolve_upstream_request_policy(self.config),
            stream=stream,
        )


def _result(payload: dict[str, Any]) -> CanonicalResult:
    response_id = str(payload.get("id") or f"resp_agentpark_{uuid.uuid4().hex}")
    result = CanonicalResult(response_id=response_id)
    output = payload.get("output")
    if not isinstance(output, list):
        raise CodexProtocolError("Responses provider response has no output array.")
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type == "message":
            content = item.get("content")
            if isinstance(content, list):
                result.text += "".join(
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict) and str(part.get("type") or "") in {"output_text", "text"}
                )
        elif item_type in {"function_call", "custom_tool_call"}:
            call_id = str(item.get("call_id") or item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            arguments = (
                json.dumps({"input": str(item.get("input") or "")}, ensure_ascii=False, separators=(",", ":"))
                if item_type == "custom_tool_call"
                else str(item.get("arguments") or "{}")
            )
            if not call_id or not name:
                raise CodexProtocolError("Responses provider tool call requires call_id and name.")
            result.tool_calls.append(CanonicalToolCall(call_id=call_id, name=name, arguments=arguments))
    if not result.text and isinstance(payload.get("output_text"), str):
        result.text = payload["output_text"]
    usage = payload.get("usage")
    if isinstance(usage, dict):
        result.input_tokens = _count(usage.get("input_tokens"))
        result.output_tokens = _count(usage.get("output_tokens"))
    return result


def _count(raw: Any) -> int:
    return int(raw) if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0


__all__ = ["ResponsesConversationAdapter"]
