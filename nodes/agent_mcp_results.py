"""MCP result normalization and explicit model-visible failure reporting."""
from __future__ import annotations

import json
from builtins import BaseExceptionGroup
from typing import Any

from nodes.agent_mcp_loader import McpServerDefinition, McpServerLoadError
from src.tool.tool_execution_result import ToolExecutionResult, build_error_result, build_success_result


def exception_summary(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(exception_summary(item) for item in exc.exceptions)
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def report_mcp_load_failure(
    agent: object,
    exc: Exception,
    *,
    phase: str,
    server: str | None = None,
    skill: str | None = None,
) -> None:
    """Discovery has no tool call ID; supply runtime data without inventing one."""
    context = {"source": "mcp", "phase": phase}
    if server is not None:
        context["server"] = server
    if skill is not None:
        context["skill"] = skill
    result = build_error_result(
        "error", error=exception_summary(exc),
        result=context,
    )
    agent.Message("user", result.model_output(), persist=False)


def normalize_mcp_call_result(result: Any) -> Any:
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


def compact_mcp_tool_result(
    *,
    server: McpServerDefinition,
    remote_tool_name: str,
    function_name: str,
    result: Any,
    agent: Any,
) -> Any:
    if isinstance(result, ToolExecutionResult) and not result.ok:
        return result
    text = _tool_result_text(result)
    limit = _mcp_tool_result_max_chars(server.config)
    if len(text) <= limit:
        return result

    payload = {
        "status": "mcp_tool_result_truncated",
        "retryable": False,
        "server": server.name,
        "tool": remote_tool_name,
        "function_name": function_name,
        "original_result_chars": len(text),
        "result_chars_limit": limit,
        "instruction": (
            "The MCP tool returned more data than this node can safely submit to the model. "
            "Use a narrower MCP query, request fewer items, or ask for a specific record."
        ),
    }
    _emit_mcp_result_compacted_notice(
        agent=agent,
        server=server.name,
        remote_tool_name=remote_tool_name,
        function_name=function_name,
        original_result_chars=len(text),
        limit=limit,
    )
    return build_success_result(json.dumps(payload, ensure_ascii=False))


def _tool_result_text(result: Any) -> str:
    if hasattr(result, "model_output") and callable(result.model_output):
        try:
            value = result.model_output()
        except Exception:
            value = result
    else:
        value = result
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value or "")


def _mcp_tool_result_max_chars(config: dict[str, Any]) -> int:
    value = (config or {}).get("toolResultMaxChars", 50000)
    if isinstance(value, bool):
        raise McpServerLoadError("MCP field toolResultMaxChars must be a positive integer")
    try:
        parsed = int(value)
    except Exception as exc:
        raise McpServerLoadError("MCP field toolResultMaxChars must be a positive integer") from exc
    if parsed <= 0:
        raise McpServerLoadError("MCP field toolResultMaxChars must be a positive integer")
    return parsed


def _emit_mcp_result_compacted_notice(
    *,
    agent: Any,
    server: str,
    remote_tool_name: str,
    function_name: str,
    original_result_chars: int,
    limit: int,
) -> None:
    emitter = getattr(agent, "_emit_provider_runtime_notice", None)
    if not callable(emitter):
        return
    emitter(
        message=json.dumps(
            {
                "policy": "mcp_tool_result_size_cap",
                "server": server,
                "tool": remote_tool_name,
                "function_name": function_name,
                "original_result_chars": int(original_result_chars),
                "limit": int(limit),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        stage="mcp_tool_result_compacted",
    )


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
