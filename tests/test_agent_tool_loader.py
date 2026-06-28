import pytest

from nodes.agent_tool_loader import ConfiguredToolLoadError
from nodes.agent_tool_loader import TOOL_NAME_LIST
from nodes.agent_tool_loader import load_configured_tools
from src.capabilities.discovery_cache import invalidate_discovery_cache
from src.tool.tool_load_errors import ToolLoadError


def test_tool_name_list_trims_and_deduplicates_case_insensitively():
    assert TOOL_NAME_LIST.parse([" read_file ", "", None, "READ_FILE", "rg_tools"]) == [
        "read_file",
        "rg_tools",
    ]


def test_load_configured_tools_loads_unique_tools_in_order():
    class Agent:
        def __init__(self):
            self.loaded = []

        def addTool(self, name):
            self.loaded.append(name)

    agent = Agent()

    load_configured_tools(agent, ["read_file", "READ_FILE", "rg_tools"])

    assert agent.loaded == ["read_file", "rg_tools"]


def test_load_configured_tools_aggregates_protocol_and_unexpected_errors():
    class Agent:
        def addTool(self, name):
            if name == "bad_protocol":
                raise ToolLoadError("bad declaration")
            raise ValueError("boom")

    with pytest.raises(ConfiguredToolLoadError) as exc:
        load_configured_tools(Agent(), ["bad_protocol", "bad_runtime"])

    message = str(exc.value)
    assert "Configured tools failed to load" in message
    assert "bad declaration" in message
    assert "Error loading tool bad_runtime: ValueError: boom" in message
    assert [failure.tool_name for failure in exc.value.failures] == ["bad_protocol", "bad_runtime"]


def test_tool_option_discovery_cache_can_be_invalidated(monkeypatch, tmp_path):
    import nodes.agent_tool_loader as tool_loader

    root = tmp_path / "functions"
    root.mkdir()
    calls = {"count": 0}

    def fake_scan(_root):
        calls["count"] += 1
        return [{"value": f"tool_{calls['count']}", "label": f"tool_{calls['count']}"}]

    invalidate_discovery_cache("tools", str(root))
    monkeypatch.setattr(tool_loader, "_list_available_tool_options_uncached", fake_scan)

    first = tool_loader.list_available_tool_options(str(root))
    second = tool_loader.list_available_tool_options(str(root))
    invalidate_discovery_cache("tools", str(root))
    third = tool_loader.list_available_tool_options(str(root))

    assert first == [{"value": "tool_1", "label": "tool_1"}]
    assert second == first
    assert third == [{"value": "tool_2", "label": "tool_2"}]
