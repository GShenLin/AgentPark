import pytest

from src.node_stream_protocol import build_node_message_delta
from src.node_stream_protocol import build_node_message_done
from src.node_stream_protocol import normalize_node_message_event


def test_node_stream_protocol_builds_message_delta_and_done():
    assert build_node_message_delta("A", "AB") == {
        "type": "node_message_delta",
        "delta": "A",
        "text": "AB",
    }
    assert build_node_message_delta("B", "AB", force=True) == {
        "type": "node_message_delta",
        "delta": "B",
        "text": "AB",
        "force": True,
    }
    assert build_node_message_done("AB") == {
        "type": "node_message_done",
        "text": "AB",
    }


def test_node_stream_protocol_normalizes_event_type_and_text():
    assert normalize_node_message_event({"type": " NODE_MESSAGE_DELTA ", "delta": None, "text": 12}) == {
        "type": "node_message_delta",
        "delta": "",
        "text": "12",
    }
    assert normalize_node_message_event({"type": "NODE_MESSAGE_DONE", "text": None}) == {
        "type": "node_message_done",
        "text": "",
    }
    assert normalize_node_message_event(
        {
            "type": "NODE_MESSAGE_DONE",
            "text": "answer",
            "response_metadata": {"protocol": "responses", "response": {"id": "resp_1"}},
        }
    ) == {
        "type": "node_message_done",
        "text": "answer",
        "response_metadata": {"protocol": "responses", "response": {"id": "resp_1"}},
    }


def test_node_stream_protocol_rejects_unknown_event():
    with pytest.raises(ValueError, match="unsupported node message event type"):
        normalize_node_message_event({"type": "delta", "text": "unsupported"})
