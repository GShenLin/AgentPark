import pytest

from nodes.agent_tool_loader import ConfiguredToolLoadError
from nodes.agent_tool_loader import load_configured_tools
from nodes.agent_tool_loader import normalize_tool_names
from src.tool_load_errors import ToolLoadError


def test_normalize_tool_names_trims_and_deduplicates_case_insensitively():
    assert normalize_tool_names([" read_file ", "", None, "READ_FILE", "rg_tools"]) == [
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
