from src.base_tool import BaseTool
from src.tool_result_processing import process_tool_result_outcome


class _DummyAgent:
    def __init__(self, config=None):
        self.config = config if isinstance(config, dict) else {}


def test_execute_tool_result_reports_invalid_timeout_without_calling_tool():
    tool = BaseTool(_DummyAgent({"toolExecutionTimeoutMsByName": {"demo_tool": "fast"}}))
    calls = {"count": 0}

    def demo_tool():
        calls["count"] += 1
        return "ok"

    tool.function_map["demo_tool"] = demo_tool

    result = tool.execute_tool_result("demo_tool", {})

    assert calls["count"] == 0
    assert result.status == "error"
    assert "toolExecutionTimeoutMsByName.demo_tool" in result.error


def test_process_tool_result_attaches_final_image_path(tmp_path):
    tool = BaseTool(_DummyAgent())
    image_path = tmp_path / "gui_feedback.png"
    image_path.write_bytes(b"png")

    cleaned, image_data = tool.process_tool_result(
        {
            "status": "done",
            "tool": "run_gui_agent_task",
            "final_image_path": str(image_path),
        }
    )

    assert isinstance(cleaned, dict)
    assert isinstance(image_data, dict)
    assert image_data.get("base64") is None
    assert image_data.get("path") == str(image_path)


def test_process_tool_result_reports_missing_final_image_path(tmp_path):
    missing = tmp_path / "missing.png"

    outcome = process_tool_result_outcome(
        {
            "status": "done",
            "tool": "run_gui_agent_task",
            "final_image_path": str(missing),
        }
    )

    assert outcome.image_data is None
    assert outcome.diagnostics == (f"final_image_path does not exist: {missing}",)


def test_tool_function_exception_is_not_retried():
    tool = BaseTool(_DummyAgent())
    calls = {"count": 0}

    def failing_tool(value):
        calls["count"] += 1
        raise ValueError(f"bad value: {value}")

    failing_tool.tool_timeout_seconds = 0
    tool.function_map["failing_tool"] = failing_tool

    result = tool.execute_tool_result("failing_tool", {"value": "x"})

    assert calls["count"] == 1
    assert result.status == "exception"
    assert result.error == "ValueError: bad value: x"
