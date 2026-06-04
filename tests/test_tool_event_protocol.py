from src.base_tool import BaseTool
from src.tool_call_protocol import ToolCallEnvelope


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
