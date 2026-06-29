import json

from src.providers.tool_feedback import ToolFeedbackMixin


class DummyFeedback(ToolFeedbackMixin):
    def __init__(self):
        self.config = {"toolResultSubmissionMaxChars": 10}
        self.messages = []
        self.notices = []

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
