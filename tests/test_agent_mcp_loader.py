import json
import socket
import subprocess
import sys
import time

import pytest


def test_mcp_server_options_read_workspace_settings():
    from nodes.agent_mcp_loader import list_available_mcp_server_options

    options = list_available_mcp_server_options(
        {
            "mcpServers": {
                "docs": {"label": "Docs", "transport": "sse"},
                "bad/name": {"label": "Bad"},
            }
        }
    )

    assert options == [{"value": "docs", "label": "Docs (sse)"}]


def test_with_mcp_caller_context_adds_companion_headers():
    from nodes.agent_mcp_loader import with_mcp_caller_context
    from src.mcp.caller_context_headers import decode_caller_header_value

    settings = {
        "mcpServers": {
            "aitools-companion": {
                "transport": "streamable-http",
                "url": "http://127.0.0.1:8788/mcp/",
                "headers": {"existing": "ok"},
            },
            "docs": {"transport": "sse", "url": "http://example.test/sse"},
        }
    }

    updated = with_mcp_caller_context(settings, graph_id="default", node_id="Agent1")

    companion = updated["mcpServers"]["aitools-companion"]
    assert companion["headers"]["existing"] == "ok"
    assert companion["headers"]["x-aitools-graph-id"].isascii()
    assert companion["headers"]["x-aitools-node-id"].isascii()
    assert decode_caller_header_value(companion["headers"]["x-aitools-graph-id"]) == "default"
    assert decode_caller_header_value(companion["headers"]["x-aitools-node-id"]) == "Agent1"
    assert "headers" not in updated["mcpServers"]["docs"]


def test_with_mcp_caller_context_supports_non_ascii_ids():
    from nodes.agent_mcp_loader import with_mcp_caller_context
    from src.mcp.caller_context_headers import decode_caller_header_value

    settings = {
        "mcpServers": {
            "aitools-companion": {
                "transport": "streamable-http",
                "url": "http://127.0.0.1:8788/mcp/",
            },
        }
    }

    updated = with_mcp_caller_context(settings, graph_id="默认图", node_id="核对答案")

    headers = updated["mcpServers"]["aitools-companion"]["headers"]
    assert headers["x-aitools-graph-id"].isascii()
    assert headers["x-aitools-node-id"].isascii()
    assert decode_caller_header_value(headers["x-aitools-graph-id"]) == "默认图"
    assert decode_caller_header_value(headers["x-aitools-node-id"]) == "核对答案"


def test_missing_configured_mcp_server_fails():
    from nodes.agent_mcp_loader import McpServerLoadError, load_mcp_server_definitions

    with pytest.raises(McpServerLoadError) as exc:
        load_mcp_server_definitions(["missing"], settings={"mcpServers": {}})

    assert "MCP server is not configured: missing" in str(exc.value)


def test_merge_mcp_server_settings_rejects_conflicting_configs():
    from nodes.agent_mcp_loader import McpServerLoadError, merge_mcp_server_settings

    with pytest.raises(McpServerLoadError) as exc:
        merge_mcp_server_settings(
            {"probe": {"command": "plugin"}},
            settings={"mcpServers": {"probe": {"command": "workspace"}}},
        )

    assert "conflicting MCP server config: probe" in str(exc.value)


def test_base_tool_registers_external_tool():
    from src.tool.base_tool import BaseTool

    class DummyAgent:
        config = {}

    tool = BaseTool(DummyAgent())
    declaration = {
        "type": "function",
        "function": {
            "name": "external_echo",
            "description": "Echo text.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    }

    def external_echo(text, agent=None):
        return {"text": text}

    tool.register_external_tool(declaration, external_echo)

    assert tool.tool_declarations == [declaration]
    assert tool.execute_tool("external_echo", {"text": "ok"}) == {"text": "ok"}


def test_mcp_materialize_records_lifecycle_success(monkeypatch):
    import nodes.agent_mcp_runtime as runtime
    from nodes.agent_mcp_loader import McpServerDefinition
    from src.mcp.lifecycle import get_mcp_lifecycle_snapshot, reset_mcp_lifecycle

    class Client:
        def __init__(self, _server):
            pass

        def list_tools(self):
            return [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object", "properties": {}}}]

    reset_mcp_lifecycle()
    monkeypatch.setattr(runtime, "McpServerClient", Client)

    tools = runtime.materialize_mcp_server_tools(
        [McpServerDefinition(name="docs", label="Docs", config={"transport": "stdio", "command": "docs"})]
    )

    assert [item.function_name for item in tools] == ["mcp__docs__echo"]
    snapshot = get_mcp_lifecycle_snapshot("docs")
    assert snapshot["state"] == "ready"
    assert snapshot["transport"] == "stdio"
    assert snapshot["tool_count"] == 1


def test_mcp_tool_list_cache_reuses_success_until_invalidated(monkeypatch):
    import nodes.agent_mcp_runtime as runtime
    from nodes.agent_mcp_loader import McpServerDefinition
    from src.mcp.lifecycle import reset_mcp_lifecycle
    from src.mcp.tool_list_cache import invalidate_mcp_tool_list_cache

    calls = {"count": 0}

    async def fake_list_tools_async(self):
        calls["count"] += 1
        return [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object", "properties": {}}}]

    server = McpServerDefinition(
        name="docs",
        label="Docs",
        config={"transport": "stdio", "command": "docs", "toolListTtlSeconds": 30},
    )
    reset_mcp_lifecycle()
    invalidate_mcp_tool_list_cache("docs")
    monkeypatch.setattr(runtime.McpServerClient, "_list_tools_async", fake_list_tools_async)

    runtime.materialize_mcp_server_tools([server])
    runtime.materialize_mcp_server_tools([server])
    invalidate_mcp_tool_list_cache("docs")
    runtime.materialize_mcp_server_tools([server])

    assert calls["count"] == 2


def test_mcp_timeout_parsing_rejects_boolean_values():
    import nodes.agent_mcp_runtime as runtime
    from nodes.agent_mcp_loader import McpServerLoadError

    with pytest.raises(McpServerLoadError, match="MCP field timeout must be a number"):
        runtime._timeout_seconds({"timeout": True}, "timeout", 30)


def test_mcp_call_read_timeout_tracks_tool_timeout_argument():
    import nodes.agent_mcp_runtime as runtime

    assert runtime._call_read_timeout({"readTimeoutSeconds": 10}, {"timeout_seconds": 600}).total_seconds() == 630
    assert runtime._call_read_timeout({"readTimeoutSeconds": 700}, {"timeout_seconds": 600}).total_seconds() == 700


def test_mcp_materialize_records_lifecycle_failure(monkeypatch):
    import nodes.agent_mcp_runtime as runtime
    from nodes.agent_mcp_loader import McpServerDefinition, McpServerLoadError
    from src.mcp.lifecycle import get_mcp_lifecycle_snapshot, reset_mcp_lifecycle

    class Client:
        def __init__(self, _server):
            pass

        def list_tools(self):
            raise McpServerLoadError("boom")

    reset_mcp_lifecycle()
    monkeypatch.setattr(runtime, "McpServerClient", Client)

    with pytest.raises(McpServerLoadError):
        runtime.materialize_mcp_server_tools(
            [McpServerDefinition(name="docs", label="Docs", config={"transport": "sse", "url": "http://example.test"})]
        )

    snapshot = get_mcp_lifecycle_snapshot("docs")
    assert snapshot["state"] == "failed"
    assert snapshot["transport"] == "sse"
    assert "boom" in snapshot["diagnostics"][0]


def test_register_mcp_server_tools_from_stdio_server(tmp_path):
    from src.tool.base_tool import BaseTool
    from nodes.agent_mcp_loader import register_mcp_server_tools

    server_script = tmp_path / "unit_mcp_server.py"
    server_script.write_text(
        "\n".join(
            [
                "from mcp.server.fastmcp import FastMCP",
                "mcp = FastMCP('unit')",
                "@mcp.tool()",
                "def echo(text: str) -> str:",
                "    return 'echo:' + text",
                "if __name__ == '__main__':",
                "    mcp.run()",
            ]
        ),
        encoding="utf-8",
    )

    class DummyAgent:
        config = {}

        def __init__(self):
            self.tools = BaseTool(self)

    agent = DummyAgent()
    settings = {
        "mcpServers": {
            "unit-server": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(server_script)],
                "readTimeoutSeconds": 10,
            }
        }
    }

    loaded = register_mcp_server_tools(agent, ["unit-server"], settings=settings)

    assert [item.name for item in loaded] == ["unit-server"]
    declaration_names = [
        item["function"]["name"]
        for item in agent.tools.tool_declarations
        if isinstance(item, dict) and isinstance(item.get("function"), dict)
    ]
    assert "mcp__unit-server__echo" in declaration_names

    result = agent.tools.execute_tool_result("mcp__unit-server__echo", {"text": "hello"})

    assert result.ok
    payload = json.loads(result.result)
    assert payload["content"][0]["type"] == "text"
    assert payload["content"][0]["text"] == "echo:hello"


def test_register_mcp_server_tools_from_streamable_http_server(tmp_path):
    result = _register_and_call_http_mcp(tmp_path, "streamable-http", "/mcp")

    assert result.ok
    payload = json.loads(result.result)
    assert payload["content"][0]["text"] == "echo:hello"


def test_register_mcp_server_tools_from_sse_server(tmp_path):
    result = _register_and_call_http_mcp(tmp_path, "sse", "/sse")

    assert result.ok
    payload = json.loads(result.result)
    assert payload["content"][0]["text"] == "echo:hello"


def _register_and_call_http_mcp(tmp_path, transport, path):
    from src.tool.base_tool import BaseTool
    from nodes.agent_mcp_loader import register_mcp_server_tools

    port = _unused_port()
    server_script = tmp_path / f"unit_mcp_{transport}.py"
    server_script.write_text(
        "\n".join(
            [
                "import sys",
                "from mcp.server.fastmcp import FastMCP",
                f"mcp = FastMCP('unit', host='127.0.0.1', port={port})",
                "@mcp.tool()",
                "def echo(text: str) -> str:",
                "    return 'echo:' + text",
                "if __name__ == '__main__':",
                f"    mcp.run(transport={transport!r})",
            ]
        ),
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [sys.executable, str(server_script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port("127.0.0.1", port)

        class DummyAgent:
            config = {}

            def __init__(self):
                self.tools = BaseTool(self)

        agent = DummyAgent()
        settings = {
            "mcpServers": {
                "unit-server": {
                    "transport": transport,
                    "url": f"http://127.0.0.1:{port}{path}",
                    "readTimeoutSeconds": 10,
                }
            }
        }

        loaded = register_mcp_server_tools(agent, ["unit-server"], settings=settings)

        assert [item.name for item in loaded] == ["unit-server"]
        assert any(
            item["function"]["name"] == "mcp__unit-server__echo"
            for item in agent.tools.tool_declarations
        )
        return agent.tools.execute_tool_result("mcp__unit-server__echo", {"text": "hello"})
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _unused_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(host, port, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            try:
                sock.connect((host, port))
                return
            except OSError:
                time.sleep(0.05)
    raise TimeoutError(f"server did not listen on {host}:{port}")
