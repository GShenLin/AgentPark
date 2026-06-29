import json


def test_responses_runtime_owns_tool_submission_recovery_feedback():
    from src.providers.openai_responses_runtime import OpenAIResponsesRuntime

    class HostWithoutToolFeedback:
        config = {"toolResultSubmissionMaxChars": 1000}

        def __init__(self):
            self.messages = [
                {
                    "role": "tool",
                    "tool_call_id": "call-heavy",
                    "name": "heavy_tool",
                    "content": "x" * 2000,
                }
            ]

    runtime = OpenAIResponsesRuntime(HostWithoutToolFeedback())

    replaced = runtime._replace_recent_tool_result_with_submission_error(
        "responses: HTTP 400: Total tokens of image and text exceed max message tokens"
    )

    assert replaced is True
    payload = json.loads(runtime.messages[0]["content"])
    assert payload["status"] == "tool_result_submission_error"
    assert payload["tool"] == "heavy_tool"
    assert payload["call_id"] == "call-heavy"
    assert payload["original_result_chars"] == 2000
