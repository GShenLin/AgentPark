import json

from src.providers.tool_feedback import ToolFeedbackMixin


class DummyFeedback(ToolFeedbackMixin):
    def __init__(self, memory_path=""):
        self.config = {"toolResultSubmissionMaxChars": 10}
        self.messages = []
        self.notices = []
        self.current_memory_path = str(memory_path or "")

    def _emit_provider_runtime_notice(self, **kwargs):
        self.notices.append(kwargs)


def test_replace_recent_tool_result_skips_already_compacted_result():
    feedback = DummyFeedback()
    feedback.messages = [
        {
            "role": "tool",
            "tool_call_id": "first",
            "name": "first_tool",
            "content": "large first result",
        },
        {
            "role": "tool",
            "tool_call_id": "second",
            "name": "second_tool",
            "content": json.dumps(
                {
                    "status": "tool_result_submission_error",
                    "tool": "second_tool",
                    "call_id": "second",
                },
                ensure_ascii=False,
            ),
        },
    ]

    replaced = feedback._replace_recent_tool_result_with_submission_error(
        "Total tokens of image and text exceed max message tokens"
    )

    assert replaced is True
    first_payload = json.loads(feedback.messages[0]["content"])
    second_payload = json.loads(feedback.messages[1]["content"])
    assert first_payload["status"] == "tool_result_submission_error"
    assert first_payload["call_id"] == "first"
    assert second_payload["call_id"] == "second"


def test_compacted_tool_result_stores_raw_artifact(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    feedback = DummyFeedback(memory_path)

    compacted = feedback._compact_tool_result_for_submission_if_needed(
        tool_name="huge_tool",
        call_id="call-big",
        content="x" * 100,
    )

    payload = json.loads(compacted)
    assert payload["status"] == "tool_result_submission_error"
    assert payload["artifact_path"]
    artifact = json.loads(open(payload["artifact_path"], "r", encoding="utf-8").read())
    assert artifact["tool"] == "huge_tool"
    assert artifact["call_id"] == "call-big"
    assert artifact["content"] == "x" * 100
