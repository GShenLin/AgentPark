import time

from src.web_backend.graph_event_stream import GraphEventStreamStore
from src.web_backend.node_live_event_publisher import NodeLiveEventPublisher
from src.web_backend.node_live_output import NodeLiveOutputStore


def test_live_publisher_coalesces_text_updates_into_one_delta_frame():
    events = GraphEventStreamStore()
    publisher = NodeLiveEventPublisher(events, interval_seconds=0.05)
    live = NodeLiveOutputStore(on_change=publisher.publish)
    try:
        live.update("test", "Agent", "a", delta="a")
        first = events.get("test")["live"]
        live.update("test", "Agent", "ab", delta="b")
        live.update("test", "Agent", "abc", delta="c")
        time.sleep(0.08)
        second = events.get("test")["live"]
    finally:
        publisher.close()

    assert first["version"] == 1
    assert second["version"] == 3
    assert second["base_version"] == 1
    assert second["stream_type"] == "delta"
    assert second["live_delta"] == "bc"


def test_live_publisher_sends_completion_without_waiting_for_next_frame():
    events = GraphEventStreamStore()
    publisher = NodeLiveEventPublisher(events, interval_seconds=1.0)
    live = NodeLiveOutputStore(on_change=publisher.publish)
    try:
        live.update("test", "Agent", "answer", delta="answer")
        live.publish_completion_event("test", "Agent", "node_message_done", {"type": "node_message_done"})
        completion = events.get("test")["live"]
    finally:
        publisher.close()

    assert completion["event_type"] == "node_message_done"
    assert completion["version"] == 2
    assert completion["stream_type"] == "snapshot"
