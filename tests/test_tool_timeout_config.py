import pytest

from src.tool.tool_timeout_config import ToolTimeoutConfigError
from src.tool.tool_timeout_config import resolve_tool_timeout_seconds


def test_resolve_tool_timeout_seconds_allows_function_override_disable_timeout():
    def long_tool():
        return None

    long_tool.tool_timeout_seconds = 0

    assert resolve_tool_timeout_seconds(config={}, name="long_running_task", func=long_tool) is None


def test_resolve_tool_timeout_seconds_prefers_named_config_override():
    def long_tool():
        return None

    long_tool.tool_timeout_seconds = 0

    assert (
        resolve_tool_timeout_seconds(
            config={"toolExecutionTimeoutSecByName": {"long_running_task": 120}},
            name="long_running_task",
            func=long_tool,
        )
        == 120
    )


def test_resolve_tool_timeout_seconds_rejects_invalid_configured_timeout():
    with pytest.raises(ToolTimeoutConfigError, match="toolExecutionTimeoutSec"):
        resolve_tool_timeout_seconds(config={"toolExecutionTimeoutSec": "soon"}, name="demo_tool")


def test_resolve_tool_timeout_seconds_rejects_boolean_timeout():
    with pytest.raises(ToolTimeoutConfigError, match="toolExecutionTimeoutSec"):
        resolve_tool_timeout_seconds(config={"toolExecutionTimeoutSec": True}, name="demo_tool")
