from src.tool.base_tool import BaseTool
from src.tool.tool_call_protocol import ToolCallEnvelope
import json


class _DummyAgent:
    def __init__(self):
        self.config = {}
        self.events = []
        self.tool_event_callback = self.events.append


def test_base_tool_emits_lifecycle_events_for_tool_call():
    agent = _DummyAgent()
    tools = BaseTool(agent)

    def echo_tool(message=None):
        return f"echo:{message}"

    tools.function_map["echo_tool"] = echo_tool
    call = ToolCallEnvelope(
        name="echo_tool",
        call_id="call-1",
        arguments={"message": "hello"},
        arguments_json='{"message":"hello"}',
        provider="unit",
    )

    execution = tools.execute_tool_call(call)

    assert execution.cleaned_result == "echo:hello"
    assert [event["type"] for event in agent.events] == ["tool_call_start", "tool_call_end"]
    assert agent.events[0]["name"] == "echo_tool"
    assert agent.events[0]["arguments"] == {"message": "hello"}
    assert agent.events[1]["status"] == "completed"
    assert agent.events[1]["duration_ms"] >= 0
    assert agent.events[1]["result_preview"] == "echo:hello"
    assert agent.events[1]["result_tail_preview"] == "echo:hello"
    assert agent.events[1]["result_chars"] == len("echo:hello")
    assert agent.events[1]["result_preview_truncated"] is False
    assert agent.events[1]["result_tail_preview_truncated"] is False


def test_base_tool_marks_large_result_preview_as_preview_truncated():
    agent = _DummyAgent()
    tools = BaseTool(agent)

    def large_tool():
        return "x" * 600

    tools.function_map["large_tool"] = large_tool
    call = ToolCallEnvelope(
        name="large_tool",
        call_id="call-large",
        arguments={},
        arguments_json="{}",
        provider="unit",
    )

    execution = tools.execute_tool_call(call)

    end_event = agent.events[-1]
    assert execution.cleaned_result == "x" * 600
    assert end_event["type"] == "tool_call_end"
    assert end_event["result_chars"] == 600
    assert end_event["result_preview_truncated"] is True
    assert end_event["result_preview"] == "x" * 500
    assert len(end_event["result_preview"]) <= 500
    assert end_event["result_tail_preview"] == "x" * 600
    assert end_event["result_tail_preview_truncated"] is False


def test_base_tool_emits_tail_preview_for_very_large_result():
    agent = _DummyAgent()
    tools = BaseTool(agent)
    result = "prefix-" + ("x" * 1500) + "-tail"

    def large_tool():
        return result

    tools.function_map["large_tool"] = large_tool
    call = ToolCallEnvelope(
        name="large_tool",
        call_id="call-tail",
        arguments={},
        arguments_json="{}",
        provider="unit",
    )

    tools.execute_tool_call(call)

    end_event = agent.events[-1]
    assert end_event["result_preview"] == result[:500]
    assert end_event["result_tail_preview"] == result[-1200:]
    assert end_event["result_tail_preview"].endswith("-tail")
    assert end_event["result_tail_preview_truncated"] is True


def test_base_tool_marks_error_result_as_error_event():
    agent = _DummyAgent()
    tools = BaseTool(agent)

    def failing_tool():
        return {"status": "error", "error": "boom"}

    tools.function_map["failing_tool"] = failing_tool
    call = ToolCallEnvelope(
        name="failing_tool",
        call_id="call-err",
        arguments={},
        arguments_json="{}",
        provider="unit",
    )

    tools.execute_tool_call(call)

    assert agent.events[-1]["type"] == "tool_call_end"
    assert agent.events[-1]["status"] == "error"
    assert "boom" in agent.events[-1]["error"]


def test_base_tool_normalizes_business_done_status_to_completed_lifecycle():
    agent = _DummyAgent()
    tools = BaseTool(agent)

    def done_tool():
        return {"status": "done", "value": 1}

    tools.function_map["done_tool"] = done_tool
    call = ToolCallEnvelope(
        name="done_tool",
        call_id="call-done",
        arguments={},
        arguments_json="{}",
        provider="unit",
    )

    execution = tools.execute_tool_call(call)

    assert execution.status == "completed"
    assert agent.events[-1]["type"] == "tool_call_end"
    assert agent.events[-1]["status"] == "completed"
    assert "error" not in agent.events[-1]


def test_base_tool_marks_raised_exception_as_structured_error_event():
    agent = _DummyAgent()
    tools = BaseTool(agent)

    def failing_tool():
        raise RuntimeError("boom")

    tools.function_map["failing_tool"] = failing_tool
    call = ToolCallEnvelope(
        name="failing_tool",
        call_id="call-exc",
        arguments={},
        arguments_json="{}",
        provider="unit",
    )

    execution = tools.execute_tool_call(call)

    assert execution.status == "exception"
    assert "RuntimeError: boom" in execution.error
    assert agent.events[-1]["type"] == "tool_call_end"
    assert agent.events[-1]["status"] == "exception"
    assert "RuntimeError: boom" in agent.events[-1]["error"]
    assert '"status": "exception"' in execution.cleaned_result


def test_base_tool_includes_result_processing_diagnostics_in_end_event(tmp_path):
    agent = _DummyAgent()
    tools = BaseTool(agent)
    missing = tmp_path / "missing.png"

    def image_tool():
        return {"status": "done", "final_image_path": str(missing)}

    tools.function_map["image_tool"] = image_tool
    call = ToolCallEnvelope(
        name="image_tool",
        call_id="call-image",
        arguments={},
        arguments_json="{}",
        provider="unit",
    )

    execution = tools.execute_tool_call(call)

    assert execution.status == "completed"
    assert execution.diagnostics == (f"final_image_path does not exist: {missing}",)
    assert agent.events[-1]["type"] == "tool_call_end"
    assert agent.events[-1]["diagnostics"] == [f"final_image_path does not exist: {missing}"]


def test_base_tool_attaches_memory_persistence_warning_from_event_callback():
    class WarningAgent(_DummyAgent):
        def __init__(self):
            super().__init__()
            self.tool_event_callback = self._on_event

        def _on_event(self, event):
            self.events.append(event)
            if event.get("type") == "tool_call_end":
                return {"memory_persistence_warning": "NodeMemoryPersistenceError: locked"}
            return None

    agent = WarningAgent()
    tools = BaseTool(agent)

    def echo_tool():
        return "hello"

    tools.function_map["echo_tool"] = echo_tool
    call = ToolCallEnvelope(
        name="echo_tool",
        call_id="call-warning",
        arguments={},
        arguments_json="{}",
        provider="unit",
    )

    execution = tools.execute_tool_call(call)

    payload = json.loads(execution.cleaned_result)
    assert payload["result"] == "hello"
    assert payload["memory_persistence_warning"] == "NodeMemoryPersistenceError: locked"
