from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Iterable

import anyio

from nodes.agent_mcp_loader import McpServerDefinition, McpServerLoadError
from src.mcp.lifecycle import mark_mcp_failed, mark_mcp_ready, mark_mcp_starting
from src.mcp.tool_list_cache import DEFAULT_MCP_TOOL_LIST_TTL_SECONDS, cached_mcp_tool_list
from src.tool.tool_execution_result import build_error_result, build_success_result
from src.value_parsing import parse_optional_float_value


@dataclass(frozen=True)
class McpMaterializedTool:
    server_name: str
    remote_tool_name: str
    function_name: str
    declaration: dict[str, Any]
    callable: Callable[..., Any]


def materialize_mcp_server_tools(servers: Iterable[McpServerDefinition]) -> list[McpMaterializedTool]:
    materialized: list[McpMaterializedTool] = []
    used_names: dict[str, str] = {}
    for server in servers or []:
        client = McpServerClient(server)
        transport = _transport_name(server.config)
        mark_mcp_starting(server.name, transport=transport)
        try:
            remote_tools = client.list_tools()
            for remote_tool in remote_tools:
                remote_name = _tool_attr(remote_tool, "name")
                if not remote_name:
                    raise McpServerLoadError(f"MCP server {server.name}: tool without a name")
                function_name = _materialized_function_name(server.name, remote_name)
                previous = used_names.get(function_name)
                identity = f"{server.name}:{remote_name}"
                if previous and previous != identity:
                    raise McpServerLoadError(
                        f"MCP tool name collision for {function_name}: {previous} and {identity}"
                    )
                used_names[function_name] = identity
                materialized.append(
                    McpMaterializedTool(
                        server_name=server.name,
                        remote_tool_name=remote_name,
                        function_name=function_name,
                        declaration=_build_tool_declaration(server, remote_tool, function_name),
                        callable=_build_tool_callable(client, remote_name, function_name),
                    )
                )
            mark_mcp_ready(server.name, transport=transport, tool_count=len(remote_tools))
        except Exception as exc:
            mark_mcp_failed(server.name, f"{type(exc).__name__}: {exc}", transport=transport)
            raise
    return materialized


class McpServerClient:
    def __init__(self, server: McpServerDefinition):
        self.server = server

    def list_tools(self) -> list[Any]:
        ttl = _timeout_seconds(self.server.config, "toolListTtlSeconds", DEFAULT_MCP_TOOL_LIST_TTL_SECONDS)
        key = {"name": self.server.name, "config": self.server.config}
        return cached_mcp_tool_list(key, lambda: anyio.run(self._list_tools_async), ttl_seconds=ttl)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return anyio.run(self._call_tool_async, tool_name, arguments, _call_read_timeout(self.server.config, arguments))

    async def _list_tools_async(self) -> list[Any]:
        async def op(session):
            result = await session.list_tools()
            return list(getattr(result, "tools", []) or [])

        return await self._with_session(op)

    async def _call_tool_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        read_timeout_override: timedelta | None = None,
    ) -> Any:
        async def op(session):
            return await session.call_tool(tool_name, arguments or {})

        result = await self._with_session(op, read_timeout_override=read_timeout_override)
        return _normalize_call_tool_result(result)

    async def _with_session(self, op: Callable[[Any], Any], *, read_timeout_override: timedelta | None = None) -> Any:
        try:
            from mcp import ClientSession
        except ImportError as exc:
            raise McpServerLoadError("Python package `mcp` is required for MCP server support.") from exc

        read_timeout = read_timeout_override or _read_timeout(self.server.config)
        transport = _transport_name(self.server.config)
        if transport == "stdio":
            from mcp.client.stdio import StdioServerParameters, stdio_client

            params = StdioServerParameters(
                command=_required_string(self.server.config, "command", self.server.name),
                args=_string_list(self.server.config.get("args"), "args", self.server.name),
                env=_string_map_optional(self.server.config.get("env"), "env", self.server.name),
                cwd=_optional_string(self.server.config.get("cwd"), "cwd", self.server.name),
            )
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream, read_timeout_seconds=read_timeout) as session:
                    await session.initialize()
                    return await op(session)

        if transport == "sse":
            from mcp.client.sse import sse_client

            async with sse_client(
                _required_string(self.server.config, "url", self.server.name),
                headers=_string_map_optional(self.server.config.get("headers"), "headers", self.server.name),
                timeout=_timeout_seconds(self.server.config, "timeout", 30),
                sse_read_timeout=_timeout_seconds(self.server.config, "sseReadTimeout", 300),
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream, read_timeout_seconds=read_timeout) as session:
                    await session.initialize()
                    return await op(session)

        if transport == "streamable-http":
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(
                _required_string(self.server.config, "url", self.server.name),
                headers=_string_map_optional(self.server.config.get("headers"), "headers", self.server.name),
                timeout=_timeout_seconds(self.server.config, "timeout", 30),
                sse_read_timeout=_timeout_seconds(self.server.config, "sseReadTimeout", 300),
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream, read_timeout_seconds=read_timeout) as session:
                    await session.initialize()
                    return await op(session)

        raise McpServerLoadError(f"MCP server {self.server.name}: unsupported transport {transport!r}")


def _build_tool_callable(client: McpServerClient, remote_tool_name: str, function_name: str) -> Callable[..., Any]:
    def call_mcp_tool(agent=None, **arguments):
        return client.call_tool(remote_tool_name, dict(arguments or {}))

    call_mcp_tool.__name__ = function_name
    call_mcp_tool.tool_timeout_seconds = 0
    return call_mcp_tool


def _build_tool_declaration(server: McpServerDefinition, remote_tool: Any, function_name: str) -> dict[str, Any]:
    remote_name = _tool_attr(remote_tool, "name")
    description = _tool_attr(remote_tool, "description")
    title = _tool_attr(remote_tool, "title")
    parameters = _tool_attr(remote_tool, "inputSchema") or {"type": "object", "properties": {}}
    if not isinstance(parameters, dict):
        raise McpServerLoadError(f"MCP server {server.name}: tool {remote_name} inputSchema must be an object")
    details = [f"MCP server: {server.name}", f"Remote tool: {remote_name}"]
    if title and title != remote_name:
        details.append(f"Title: {title}")
    if description:
        details.append(str(description))
    return {
        "type": "function",
        "function": {
            "name": function_name,
            "description": "\n".join(details),
            "parameters": parameters,
        },
    }


def _normalize_call_tool_result(result: Any) -> Any:
    payload = {
        "content": [_content_to_json(item) for item in getattr(result, "content", []) or []],
    }
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        payload["structuredContent"] = structured
    meta = getattr(result, "meta", None)
    if meta:
        payload["_meta"] = meta
    if bool(getattr(result, "isError", False)):
        return build_error_result("error", error=_first_content_text(payload) or "MCP tool returned isError=true", result=payload)
    return build_success_result(json.dumps(payload, ensure_ascii=False))


def _content_to_json(item: Any) -> Any:
    if hasattr(item, "model_dump"):
        return item.model_dump(by_alias=True, exclude_none=True)
    if isinstance(item, dict):
        return dict(item)
    return item


def _first_content_text(payload: dict[str, Any]) -> str:
    for item in payload.get("content") or []:
        if isinstance(item, dict) and str(item.get("type") or "") == "text":
            text = str(item.get("text") or "").strip()
            if text:
                return text
    return ""


def _tool_attr(tool: Any, name: str) -> Any:
    if isinstance(tool, dict):
        return tool.get(name)
    return getattr(tool, name, None)


def _materialized_function_name(server_name: str, tool_name: str) -> str:
    return f"mcp__{_safe_function_part(server_name)}__{_safe_function_part(tool_name)}"


def _safe_function_part(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise McpServerLoadError("MCP server/tool name cannot be converted to a provider-safe function name")
    return text


def _transport_name(config: dict[str, Any]) -> str:
    value = str(config.get("transport") or config.get("type") or "stdio").strip().lower().replace("_", "-")
    if value == "http":
        return "streamable-http"
    return value


def _read_timeout(config: dict[str, Any]) -> timedelta | None:
    value = config.get("readTimeoutSeconds", config.get("read_timeout_seconds"))
    if value in (None, ""):
        return None
    return timedelta(seconds=_positive_float(value, "readTimeoutSeconds"))


def _call_read_timeout(config: dict[str, Any], arguments: dict[str, Any]) -> timedelta | None:
    configured = _read_timeout(config)
    if not isinstance(arguments, dict):
        return configured
    raw = arguments.get("timeout_seconds")
    if raw in (None, ""):
        return configured
    try:
        requested = _positive_float(raw, "timeout_seconds") + 30.0
    except McpServerLoadError:
        return configured
    if configured is None or requested > configured.total_seconds():
        return timedelta(seconds=requested)
    return configured


def _timeout_seconds(config: dict[str, Any], key: str, default: float) -> float:
    value = config.get(key)
    if value in (None, ""):
        return float(default)
    return _positive_float(value, key)


def _positive_float(value: Any, field: str) -> float:
    try:
        parsed = parse_optional_float_value(f"MCP field {field}", value, minimum_exclusive=0)
    except ValueError as exc:
        raise McpServerLoadError(str(exc)) from exc
    if parsed is None:
        raise McpServerLoadError(f"MCP field {field} must be a positive number")
    return parsed


def _required_string(config: dict[str, Any], field: str, server_name: str) -> str:
    value = _optional_string(config.get(field), field, server_name)
    if not value:
        raise McpServerLoadError(f"MCP server {server_name}: field {field} is required")
    return value


def _optional_string(value: Any, field: str, server_name: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise McpServerLoadError(f"MCP server {server_name}: field {field} must be a string")
    return value.strip()


def _string_list(value: Any, field: str, server_name: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise McpServerLoadError(f"MCP server {server_name}: field {field} must be a string array")
    return [item for item in value]


def _string_map_optional(value: Any, field: str, server_name: str) -> dict[str, str] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise McpServerLoadError(f"MCP server {server_name}: field {field} must be an object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise McpServerLoadError(f"MCP server {server_name}: field {field} must contain string values")
        result[key] = item
    return result
