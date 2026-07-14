from __future__ import annotations

import json

from src.cli_commands.companion_live_events import CompanionLiveEventReducer


def test_live_event_reducer_preserves_thinking_tool_answer_sequence():
    reducer = CompanionLiveEventReducer()

    thinking = reducer.consume(
        {"type": "node_thinking_delta", "delta": "Inspecting", "text": "Inspecting"}
    )
    tool = reducer.consume({"type": "tool_call_start", "name": "read_file", "call_id": "call-1"})
    answer = reducer.consume(
        {"type": "node_message_delta", "delta": "Done", "text": "Done"}
    )
    done = reducer.consume({"type": "node_message_done", "text": "Done"})

    assert [(item.kind, item.channel, item.text) for item in thinking] == [
        ("delta", "thinking", "Inspecting")
    ]
    assert tool[0].kind == "tool"
    assert tool[0].event == {"type": "tool_call_start", "name": "read_file", "call_id": "call-1"}
    assert [(item.kind, item.channel, item.text) for item in answer] == [
        ("delta", "assistant", "Done")
    ]
    assert [(item.kind, item.text) for item in done] == [("close", "")]


def test_live_event_reducer_derives_delta_from_cumulative_text_without_duplicates():
    reducer = CompanionLiveEventReducer()

    first = reducer.consume({"type": "node_message_delta", "delta": "Hel", "text": "Hel"})
    second = reducer.consume({"type": "node_message_delta", "delta": "lo", "text": "Hello"})
    repeated = reducer.consume({"type": "node_message_delta", "delta": "", "text": "Hello"})

    assert first[0].text == "Hel"
    assert second[0].text == "lo"
    assert repeated == []
    assert reducer.answer_text == "Hello"


def test_live_event_reducer_matches_web_live_search_activity_format():
    reducer = CompanionLiveEventReducer()
    event = {
        "type": "runtime_notice",
        "stage": "openai_chat_native_web_search",
        "message": json.dumps(
            {
                "event": "native_web_search",
                "preview": {"query": "AgentPark", "status": "running"},
            }
        ),
    }

    actions = reducer.consume(event)

    assert len(actions) == 1
    assert actions[0].kind == "activity"
    assert actions[0].text == "Web search: AgentPark (running)"


def test_live_event_reducer_exposes_server_tool_activity():
    reducer = CompanionLiveEventReducer()
    event = {
        "type": "server_tool_activity",
        "call_id": "search-1",
        "tool_type": "web_search",
        "status": "completed",
    }

    actions = reducer.consume(event)

    assert len(actions) == 1
    assert actions[0].kind == "server_tool"
    assert actions[0].event == event
