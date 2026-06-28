import inspect

import pytest

from src.channels.errors import ChannelConfigError, ChannelError
from src.web_backend.channel_api import call_channel_http, channel_http_endpoint
from src.web_backend.shared import HTTPException


def test_channel_http_endpoint_preserves_handler_signature():
    def handler(graph_id: str, node_id: str, payload: dict | None = None):
        return {"graph_id": graph_id, "node_id": node_id, "payload": payload}

    endpoint = channel_http_endpoint(handler)

    assert inspect.signature(endpoint) == inspect.signature(handler)
    assert endpoint("g", "n", {"action": "status"}) == {
        "graph_id": "g",
        "node_id": "n",
        "payload": {"action": "status"},
    }


def test_channel_http_endpoint_maps_channel_config_error():
    def handler():
        raise ChannelConfigError("bad config")

    with pytest.raises(HTTPException) as exc:
        channel_http_endpoint(handler)()

    assert exc.value.status_code == 400
    assert exc.value.detail == "bad config"


def test_call_channel_http_maps_channel_config_error():
    def handler():
        raise ChannelConfigError("bad config")

    with pytest.raises(HTTPException) as exc:
        call_channel_http(handler)

    assert exc.value.status_code == 400
    assert exc.value.detail == "bad config"


def test_channel_http_endpoint_maps_channel_runtime_error():
    def handler():
        raise ChannelError("driver failed")

    with pytest.raises(HTTPException) as exc:
        channel_http_endpoint(handler)()

    assert exc.value.status_code == 502
    assert exc.value.detail == "driver failed"
