import json
import queue
import threading
from unittest.mock import Mock

import pytest

from src.desktop_capture.contracts import CapturedFrame
from src.providers.openai_realtime_screen import OpenAIRealtimeScreen

FRAME = CapturedFrame(display_id='display', captured_at='2026-10-14T00:00:00Z',
                      width=800, height=450, image='data:image/jpeg;base64,YQ==')


class Socket:
    def __init__(self):
        self.events = queue.Queue()
        self.sent = []
        self.reject = False

    def send(self, raw):
        event = json.loads(raw)
        self.sent.append(event)
        if self.reject:
            self.events.put(json.dumps({'type': 'error', 'error': {'event_id': event['event_id'], 'message': 'Image rejected'}}))
        elif event['type'] == 'conversation.item.create':
            self.events.put(json.dumps({'type': 'conversation.item.added', 'item': {'id': event['item']['id']}}))
        else:
            self.events.put(json.dumps({'type': 'conversation.item.deleted', 'item_id': event['item_id']}))

    def __iter__(self):
        while True:
            event = self.events.get(timeout=5)
            if event is None: return
            yield event

    def close(self):
        self.events.put(None)


@pytest.fixture
def sink(monkeypatch):
    socket = Socket()
    connect = Mock(return_value=socket)
    monkeypatch.setattr('src.providers.openai_realtime_screen.connect', connect)
    sink = OpenAIRealtimeScreen('/v1/realtime/calls/rtc_test', 'Bearer secret')
    yield sink, socket, connect
    sink.close()
    if sink.reader: sink.reader.join(timeout=2)


def test_direct_image_delivery_and_stop_preserve_audio_session(sink):
    channel, socket, connect = sink
    connect.assert_not_called()  # Starting voice doesn't require a screen connection.
    identity = channel.publish('share', FRAME, lambda: True)
    assert isinstance(identity, str) and 'data:' not in identity
    assert socket.sent[0]['item']['content'][1]['image_url'] == FRAME.image
    description = socket.sent[0]['item']['content'][0]['text']
    for value in [identity, 'display_id=display', 'image_width=800', 'image_height=450']:
        assert value in description
    assert not any(event['type'] in {'response.create', 'session.update'} for event in socket.sent)
    assert not channel.closed


def test_provider_rejection_is_returned_without_closing_call(sink):
    channel, socket, _ = sink
    socket.reject = True
    with pytest.raises(RuntimeError, match='Image rejected'):
        channel.publish('share', FRAME, lambda: True)
    assert not channel.closed


def test_stop_while_connecting_never_sends_the_captured_image(sink):
    channel, socket, _ = sink
    with pytest.raises(RuntimeError, match='通话已结束'):
        channel.publish('share', FRAME, lambda: False)
    assert socket.sent == []


def test_history_is_bounded_and_only_owned_items_are_deleted(sink):
    channel, socket, _ = sink
    first = channel.publish('share', FRAME, lambda: True)
    for _ in range(20): channel.publish('share', FRAME, lambda: True)
    deletes = [event for event in socket.sent if event['type'] == 'conversation.item.delete']
    assert len(channel.items) == 20 and [event['item_id'] for event in deletes] == [first]


def test_disconnection_unblocks_pending_publish(sink):
    channel, socket, _ = sink
    socket.send = lambda _raw: socket.close()
    with pytest.raises(RuntimeError, match='断开'):
        channel.publish('share', FRAME, lambda: True)
    assert not channel.pending
