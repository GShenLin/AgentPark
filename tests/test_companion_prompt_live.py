from __future__ import annotations

from src.cli_commands.companion_prompt_live import PromptLiveTranscript


def test_prompt_live_transcript_accumulates_thinking_deltas_without_replacement():
    invalidations = []
    live = PromptLiveTranscript(lambda: invalidations.append(True))

    live.handle({"type": "node_thinking_delta", "delta": "I need ", "text": "I need "})
    live.handle(
        {
            "type": "node_thinking_delta",
            "delta": "to inspect the file.",
            "text": "I need to inspect the file.",
        }
    )

    rendered = "".join(fragment[1] for fragment in live.prompt_message())
    assert "I need to inspect the file." in rendered
    assert rendered.count("I need ") == 1
    assert len(invalidations) == 2


def test_prompt_live_transcript_preserves_thinking_tool_answer_order_and_commits():
    live = PromptLiveTranscript(lambda: None)

    live.handle({"type": "node_thinking_delta", "delta": "Inspecting", "text": "Inspecting"})
    live.handle({"type": "tool_call_start", "name": "read_file", "call_id": "call-1"})
    live.handle({"type": "tool_call_end", "name": "read_file", "call_id": "call-1", "status": "completed"})
    live.handle({"type": "node_message_delta", "delta": "Found it", "text": "Found it"})
    live.handle({"type": "node_message_done", "text": "Found it"})

    committed = live.commit()

    assert committed.index("thinking") < committed.index("Inspecting")
    assert committed.index("Inspecting") < committed.index("tool read_file: running")
    assert committed.index("tool read_file: completed") < committed.index("assistant")
    assert committed.index("assistant") < committed.index("Found it")
    assert live.prompt_message() == [("class:prompt", "> ")]
