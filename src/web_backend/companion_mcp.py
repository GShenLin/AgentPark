from __future__ import annotations

import logging
from functools import partial
from typing import Any

import anyio
from mcp.server.fastmcp import Context, FastMCP

from src.mcp.caller_context_headers import decode_caller_header_value

from .companion_mcp_guidance import COMPANION_MCP_INSTRUCTIONS
from .companion_mcp_errors import companion_error_from_exception
from .companion_mcp_links import CompanionMcpLinkTools
from .companion_mcp_tools import CompanionMcpTools


class _TerminatingNoneSessionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return str(record.getMessage()).strip() != "Terminating session: None"


def _install_companion_log_filters() -> None:
    marker = "_aitools_companion_filter_installed"
    root = logging.getLogger()
    if bool(getattr(root, marker, False)):
        return
    session_filter = _TerminatingNoneSessionFilter()
    root.addFilter(session_filter)
    for name in ("mcp", "mcp.server", "mcp.server.streamable_http", "uvicorn.error"):
        logging.getLogger(name).addFilter(session_filter)
    setattr(root, marker, True)


async def _run_blocking_tool(func, /, *args, **kwargs) -> Any:
    try:
        return await anyio.to_thread.run_sync(partial(func, *args, **kwargs))
    except Exception as exc:
        return companion_error_from_exception(exc).to_result()


def _caller_from_context(ctx: Context | None) -> dict[str, str]:
    if ctx is None:
        return {}
    try:
        request = ctx.request_context.request
    except Exception:
        return {}
    headers = getattr(request, "headers", None)
    if headers is None:
        return {}

    def header(name: str) -> str:
        try:
            return decode_caller_header_value(headers.get(name) or "").strip()
        except (TypeError, ValueError):
            return ""

    return {
        "graph_id": header("x-aitools-graph-id"),
        "node_id": header("x-aitools-node-id"),
    }


def build_companion_mcp(core: object) -> FastMCP:
    _install_companion_log_filters()
    mcp = FastMCP(
        "aitools-companion",
        instructions=COMPANION_MCP_INSTRUCTIONS,
        streamable_http_path="/",
        stateless_http=True,
    )
    tools = CompanionMcpTools(core)
    link_tools = CompanionMcpLinkTools(core)

    @mcp.tool(name="get_companion_meta")
    async def get_companion_meta(ctx: Context) -> dict[str, Any]:
        """Return Companion service metadata and the calling node identity when available."""
        return await _run_blocking_tool(tools.get_companion_meta, caller=_caller_from_context(ctx))

    @mcp.tool(name="list_graph")
    async def list_graph() -> dict[str, Any]:
        """List available AgentPark graphs."""
        return await _run_blocking_tool(tools.list_graph)

    @mcp.tool(name="list_node")
    async def list_node(graph_id: str = "default", ctx: Context | None = None) -> dict[str, Any]:
        """List node instance configs with capability summaries for a graph."""
        return await _run_blocking_tool(tools.list_node, graph_id=graph_id, caller=_caller_from_context(ctx))

    @mcp.tool(name="list_node_status")
    async def list_node_status(graph_id: str = "default", ctx: Context | None = None) -> dict[str, Any]:
        """Return compact state, last message, errors, and capabilities for all nodes in a graph."""
        return await _run_blocking_tool(tools.list_node_status, graph_id=graph_id, caller=_caller_from_context(ctx))

    @mcp.tool(name="list_link")
    async def list_link(graph_id: str = "default") -> dict[str, Any]:
        """List node links for one graph."""
        return await _run_blocking_tool(link_tools.list_link, graph_id=graph_id)

    @mcp.tool(name="connect_node")
    async def connect_node(
        graph_id: str = "default",
        from_node: str = "",
        to_node: str = "",
        from_output_index: int = 0,
        to_input_index: int = 0,
    ) -> dict[str, Any]:
        """Create a directed link between two nodes in one graph."""
        return await _run_blocking_tool(
            link_tools.connect_node,
            graph_id=graph_id,
            from_node=from_node,
            to_node=to_node,
            from_output_index=from_output_index,
            to_input_index=to_input_index,
        )

    @mcp.tool(name="disconnect_node")
    async def disconnect_node(
        graph_id: str = "default",
        link_id: str = "",
        from_node: str = "",
        to_node: str = "",
        from_output_index: int = 0,
        to_input_index: int = 0,
    ) -> dict[str, Any]:
        """Remove a graph link by link_id or by exact endpoints."""
        return await _run_blocking_tool(
            link_tools.disconnect_node,
            graph_id=graph_id,
            link_id=link_id,
            from_node=from_node,
            to_node=to_node,
            from_output_index=from_output_index,
            to_input_index=to_input_index,
        )

    @mcp.tool(name="change_node_config")
    async def change_node_config(graph_id: str = "default", node_id: str = "", fields: dict[str, Any] | None = None) -> dict[str, Any]:
        """Change editable config fields on one node instance."""
        return await _run_blocking_tool(tools.change_node_config, graph_id=graph_id, node_id=node_id, fields=fields or {})

    @mcp.tool(name="send_message_to_node")
    async def send_message_to_node(
        graph_id: str = "default",
        node_id: str = "",
        message: str = "",
        wait_until_idle: bool = True,
        timeout_seconds: float = 120,
        clear_history: bool = False,
        allow_self_recursion: bool = False,
        response_format: dict[str, Any] | str | None = None,
        working_directory: str = "",
        allowed_tools: list[str] | None = None,
        system_prompt_append: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Send a text message to a node and optionally wait for the final idle result."""
        return await _run_blocking_tool(
            tools.send_message_to_node,
            graph_id=graph_id,
            node_id=node_id,
            message=message,
            wait_until_idle=wait_until_idle,
            timeout_seconds=timeout_seconds,
            clear_history=clear_history,
            allow_self_recursion=allow_self_recursion,
            response_format=response_format,
            working_directory=working_directory,
            allowed_tools=allowed_tools,
            system_prompt_append=system_prompt_append,
            caller=_caller_from_context(ctx),
        )

    @mcp.tool(name="get_node_last_message")
    async def get_node_last_message(
        graph_id: str = "default",
        node_id: str = "",
        wait_until_idle: bool = False,
        timeout_seconds: float = 0,
        since_message_id: str = "",
    ) -> dict[str, Any]:
        """Read node state; since_message_id is treated as node_event_seq when numeric."""
        return await _run_blocking_tool(
            tools.get_node_last_message,
            graph_id=graph_id,
            node_id=node_id,
            wait_until_idle=wait_until_idle,
            timeout_seconds=timeout_seconds,
            since_message_id=since_message_id,
        )

    @mcp.tool(name="get_node_memory")
    async def get_node_memory(
        graph_id: str = "default",
        node_id: str = "",
        max_chars: int = 20000,
        start_seq: int = 0,
        offset_chars: int = 0,
    ) -> dict[str, Any]:
        """Read recent node memory when last_message is only a short final preview."""
        return await _run_blocking_tool(
            tools.get_node_memory,
            graph_id=graph_id,
            node_id=node_id,
            max_chars=max_chars,
            start_seq=start_seq,
            offset_chars=offset_chars,
        )

    @mcp.tool(name="stop_node")
    async def stop_node(graph_id: str, node_id: str, reason: str = "") -> dict[str, Any]:
        """Request cancellation and clear queued work for a stuck node."""
        return await _run_blocking_tool(tools.stop_node, graph_id=graph_id, node_id=node_id, reason=reason)

    @mcp.tool(name="get_working_node")
    async def get_working_node(graph_id: str = "", ctx: Context | None = None) -> dict[str, Any]:
        """List nodes currently in the working state."""
        return await _run_blocking_tool(tools.get_working_node, graph_id=graph_id, caller=_caller_from_context(ctx))

    return mcp


__all__ = ["CompanionMcpTools", "build_companion_mcp"]
