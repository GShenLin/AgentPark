from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .contracts import CanonicalTool
from .contracts import CodexProtocolError
from .http_transport import UpstreamResponse


@dataclass(frozen=True)
class ResponsesToolIdentity:
    namespace: str
    name: str


@dataclass(frozen=True)
class PreparedResponsesRequest:
    payload: dict[str, Any]
    tools_by_wire_name: dict[str, ResponsesToolIdentity]


class ResponsesPassthrough:
    """Preserve Codex Responses semantics across provider-specific dialects."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)

    @property
    def flattens_namespace_tools(self) -> bool:
        provider_type = str(self.config.get("type") or "").strip().lower()
        return provider_type in {"doubao", "grok"}

    def prepare_request(self, payload: dict[str, Any]) -> PreparedResponsesRequest:
        request = copy.deepcopy(payload)
        if not self.flattens_namespace_tools:
            return PreparedResponsesRequest(payload=request, tools_by_wire_name={})

        tools, identities = _flatten_namespace_tools(request.get("tools"))
        if tools is not None:
            request["tools"] = tools
        _flatten_tool_choice(request, identities)
        _flatten_input_calls(request.get("input"), identities)
        _remove_unsupported_reasoning_summary(request)
        request.pop("client_metadata", None)
        return PreparedResponsesRequest(payload=request, tools_by_wire_name=identities)

    @staticmethod
    def transform_response(
        payload: dict[str, Any],
        tools_by_wire_name: dict[str, ResponsesToolIdentity],
    ) -> dict[str, Any]:
        response = copy.deepcopy(payload)
        _restore_calls(response, tools_by_wire_name)
        return response

    @staticmethod
    def transform_stream(
        response: UpstreamResponse,
        tools_by_wire_name: dict[str, ResponsesToolIdentity],
    ) -> Iterable[bytes]:
        try:
            frame: list[bytes] = []
            while True:
                line = response.body.readline()
                if not line:
                    if frame:
                        yield _transform_sse_frame(frame, tools_by_wire_name)
                    return
                frame.append(line)
                if line.rstrip(b"\r\n"):
                    continue
                yield _transform_sse_frame(frame, tools_by_wire_name)
                frame.clear()
        finally:
            response.close()


def _flatten_namespace_tools(
    raw_tools: object,
) -> tuple[list[Any] | None, dict[str, ResponsesToolIdentity]]:
    if raw_tools is None:
        return None, {}
    if not isinstance(raw_tools, list):
        raise CodexProtocolError("Responses tools must be an array.")
    output: list[Any] = []
    identities: dict[str, ResponsesToolIdentity] = {}
    for raw in raw_tools:
        if not isinstance(raw, dict):
            raise CodexProtocolError("Every Responses tool must be an object.")
        if str(raw.get("type") or "").strip() != "namespace":
            output.append(copy.deepcopy(raw))
            continue
        namespace = _required_text(raw, "name", "namespace tool")
        children = raw.get("tools")
        if not isinstance(children, list) or not children:
            raise CodexProtocolError(f"namespace tool {namespace!r} must contain function tools.")
        for child in children:
            if not isinstance(child, dict) or str(child.get("type") or "").strip() != "function":
                raise CodexProtocolError(f"namespace tool {namespace!r} supports only function children.")
            name = _required_text(child, "name", f"namespace tool {namespace!r} child")
            schema = child.get("parameters")
            if not isinstance(schema, dict):
                raise CodexProtocolError(f"namespace tool {namespace!r} child {name!r} parameters must be an object.")
            wire_name = CanonicalTool(
                name=name,
                namespace=namespace,
                description=str(child.get("description") or ""),
                input_schema=schema,
            ).wire_name
            if wire_name in identities or any(
                isinstance(item, dict) and str(item.get("name") or "") == wire_name
                for item in output
            ):
                raise CodexProtocolError(f"Responses tools collide after namespace flattening: {wire_name!r}.")
            identities[wire_name] = ResponsesToolIdentity(namespace=namespace, name=name)
            output.append(
                {
                    "type": "function",
                    "name": wire_name,
                    "description": str(child.get("description") or ""),
                    "parameters": copy.deepcopy(schema),
                }
            )
    return output, identities


def _flatten_tool_choice(
    request: dict[str, Any],
    identities: dict[str, ResponsesToolIdentity],
) -> None:
    choice = request.get("tool_choice")
    if not isinstance(choice, dict):
        return
    namespace = str(choice.get("namespace") or "").strip()
    name = str(choice.get("name") or "").strip()
    if not namespace or not name:
        return
    wire_name = _wire_name_for_identity(identities, namespace=namespace, name=name)
    flattened = dict(choice)
    flattened["name"] = wire_name
    flattened.pop("namespace", None)
    request["tool_choice"] = flattened


def _flatten_input_calls(
    raw_input: object,
    identities: dict[str, ResponsesToolIdentity],
) -> None:
    if not isinstance(raw_input, list):
        return
    for item in raw_input:
        if not isinstance(item, dict) or str(item.get("type") or "") != "function_call":
            continue
        namespace = str(item.get("namespace") or "").strip()
        name = str(item.get("name") or "").strip()
        if not namespace or not name:
            continue
        item["name"] = _wire_name_for_identity(identities, namespace=namespace, name=name)
        item.pop("namespace", None)


def _remove_unsupported_reasoning_summary(request: dict[str, Any]) -> None:
    reasoning = request.get("reasoning")
    if not isinstance(reasoning, dict) or "summary" not in reasoning:
        return
    normalized = dict(reasoning)
    normalized.pop("summary", None)
    if normalized:
        request["reasoning"] = normalized
    else:
        request.pop("reasoning", None)


def _restore_calls(
    value: object,
    identities: dict[str, ResponsesToolIdentity],
) -> None:
    if isinstance(value, list):
        for item in value:
            _restore_calls(item, identities)
        return
    if not isinstance(value, dict):
        return
    if str(value.get("type") or "") == "function_call":
        identity = identities.get(str(value.get("name") or ""))
        if identity is not None:
            value["name"] = identity.name
            value["namespace"] = identity.namespace
    for child in value.values():
        _restore_calls(child, identities)


def _transform_sse_frame(
    lines: list[bytes],
    identities: dict[str, ResponsesToolIdentity],
) -> bytes:
    data_lines: list[bytes] = []
    other_lines: list[bytes] = []
    newline = b"\n"
    for line in lines:
        if line.endswith(b"\r\n"):
            newline = b"\r\n"
        stripped = line.rstrip(b"\r\n")
        if stripped.startswith(b"data:"):
            data_lines.append(stripped[5:].lstrip())
        elif stripped:
            other_lines.append(stripped)
    if not data_lines:
        return newline.join(other_lines) + newline + newline
    raw_data = b"\n".join(data_lines)
    if raw_data == b"[DONE]":
        transformed_data = raw_data
    else:
        try:
            payload = json.loads(raw_data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexProtocolError("Responses SSE data is not valid UTF-8 JSON.") from exc
        _restore_calls(payload, identities)
        transformed_data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return newline.join([*other_lines, b"data: " + transformed_data]) + newline + newline


def _wire_name_for_identity(
    identities: dict[str, ResponsesToolIdentity],
    *,
    namespace: str,
    name: str,
) -> str:
    matches = [
        wire_name
        for wire_name, identity in identities.items()
        if identity.namespace == namespace and identity.name == name
    ]
    if len(matches) != 1:
        raise CodexProtocolError(
            f"Responses namespace tool choice/call cannot be flattened uniquely: {namespace!r}.{name!r}."
        )
    return matches[0]


def _required_text(payload: dict[str, Any], key: str, owner: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise CodexProtocolError(f"{owner} requires non-empty {key}.")
    return value


__all__ = [
    "PreparedResponsesRequest",
    "ResponsesPassthrough",
    "ResponsesToolIdentity",
]
