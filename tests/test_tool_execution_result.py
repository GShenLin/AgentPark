import json

from src.tool.tool_execution_result import build_error_result
from src.tool.tool_execution_result import build_cancellation_failed_result
from src.tool.tool_execution_result import build_cancellation_failed_result
from src.tool.tool_execution_result import build_user_stopped_result
from src.tool.tool_execution_result import normalize_tool_execution_result
from src.tool.tool_execution_result import status_and_error_from_payload


def test_business_success_statuses_normalize_to_completed_lifecycle_status():
    for status in ("ok", "done", "success", "completed", ""):
        result = normalize_tool_execution_result({"status": status, "value": 1}, tool_name="demo_tool")

        assert result.status == "completed"
        assert result.ok
        assert result.model_output() == {"status": status, "value": 1}


def test_terminal_error_statuses_preserve_error_for_model_output():
    result = normalize_tool_execution_result(
        {"status": "permission_denied", "reason": "no access"},
        tool_name="demo_tool",
    )

    assert result.status == "permission_denied"
    assert not result.ok
    payload = json.loads(result.model_output())
    assert payload["status"] == "permission_denied"
    assert payload["tool"] == "demo_tool"
    assert payload["error"] == "no access"


def test_string_json_payload_status_is_interpreted_by_execution_protocol():
    status, error = status_and_error_from_payload('{"status":"timeout","error":"slow"}')

    assert status == "timeout"
    assert error == "slow"


def test_explicit_error_result_builds_structured_model_output():
    result = build_error_result("exception", tool_name="demo_tool", error="ValueError: bad")

    payload = json.loads(result.model_output())
    assert payload == {
        "status": "exception",
        "tool": "demo_tool",
        "error": "ValueError: bad",
    }


def test_user_stopped_tool_call_returns_exact_protocol_result():
    result = build_user_stopped_result(tool_name="demo_tool")

    assert result.status == "stopped"
    assert result.error is None
    assert result.model_output() == "UserStoppedThisCall"


def test_uncooperative_tool_cancellation_is_not_reported_as_user_stopped():
    result = build_cancellation_failed_result(tool_name="demo_tool")

    assert result.status == "cancellation_failed"
    assert result.model_output() != "UserStoppedThisCall"
    payload = json.loads(result.model_output())
    assert payload["status"] == "cancellation_failed"
    assert payload["tool"] == "demo_tool"


def test_cancellation_failure_is_not_reported_as_user_stopped():
    result = build_cancellation_failed_result(tool_name="demo_tool")

    payload = json.loads(result.model_output())
    assert payload["status"] == "cancellation_failed"
    assert payload["tool"] == "demo_tool"
    assert payload["error"] == "Tool did not stop after cancellation was requested."
