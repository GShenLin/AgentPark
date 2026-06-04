import pytest

from src.tool_timeout_config import ToolTimeoutConfigError
from src.tool_timeout_config import resolve_tool_timeout_seconds


def test_resolve_tool_timeout_seconds_allows_function_override_disable_timeout():
    def gui_tool():
        return None

    gui_tool.tool_timeout_seconds = 0

    assert resolve_tool_timeout_seconds(config={}, name="run_gui_agent_task", func=gui_tool) is None


def test_resolve_tool_timeout_seconds_prefers_named_config_override():
    def gui_tool():
        return None

    gui_tool.tool_timeout_seconds = 0

    assert (
        resolve_tool_timeout_seconds(
            config={"toolExecutionTimeoutSecByName": {"run_gui_agent_task": 120}},
            name="run_gui_agent_task",
            func=gui_tool,
        )
        == 120
    )


def test_resolve_tool_timeout_seconds_rejects_invalid_configured_timeout():
    with pytest.raises(ToolTimeoutConfigError, match="toolExecutionTimeoutSec"):
        resolve_tool_timeout_seconds(config={"toolExecutionTimeoutSec": "soon"}, name="demo_tool")
