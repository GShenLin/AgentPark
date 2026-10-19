import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.desktop_capture.contracts import CapturedFrame
from src.providers.doubao_voice import DoubaoVoiceProvider
from src.providers.openai_realtime_voice import OpenAIRealtimeVoiceProvider, voice_session
from src.providers.voice_provider import VoiceProvider
from src.providers.voice_tools import VoiceToolResult
from src.providers.volcengine_rtc_voice import VolcengineRtcVoiceProvider
from src.providers.volcengine_rtc_screen import VolcengineRtcScreen
from src.providers.volcengine_rtc_session import VolcengineRtcSession
from src.voice_settings import VoiceSettings


def test_every_provider_inherits_same_tools_and_rtc_only_changes_wire_format():
    expected = VoiceProvider.tools()
    assert {tool['name'] for tool in expected} == {
        'delegate_to_node', 'capture_execution_screen', 'annotate_screen', 'read_composer_input', 'edit_composer_input'}
    for provider in [OpenAIRealtimeVoiceProvider, DoubaoVoiceProvider, VolcengineRtcVoiceProvider]:
        assert provider.tools is VoiceProvider.tools
        assert provider.tools() == expected
    # One session's protocol transformation must not mutate the shared catalog.
    first = VoiceProvider.tools(); first[0]['parameters']['properties'].clear()
    assert VoiceProvider.tools() == expected
    assert voice_session('history', VoiceSettings())['tools'] == expected

    async def rtc():
        session = VolcengineRtcSession(Mock(), 'app', 'room', 'user', 'bot', 'history', VoiceSettings())
        try:
            config = session._configuration()['LLMConfig']
            assert config['Tools'] == [{'type': 'function', 'function': {k: v for k, v in t.items() if k != 'type'}} for t in expected]
            assert config['SystemMessages'] == [VoiceProvider.instructions('history')]
            assert config['VisionConfig']['Enable'] is True
        finally:
            await session.aclose()
    asyncio.run(rtc())


def test_rtc_single_image_fragments_go_to_bot_with_one_final_image_prompt():
    api = Mock(); api.post_json.return_value = {'Result': {'Message': 'Success'}}
    session = SimpleNamespace(api=api, identity={'AppId': 'app', 'RoomId': 'room'}, bot='bot', started=True, closed=False)
    sink = VolcengineRtcScreen(session)
    data = base64.b64encode(b'x' * 100000).decode()
    frame = CapturedFrame(display_id='display', captured_at='now', width=1600, height=900, image='data:image/jpeg;base64,' + data)
    identity = sink.publish('call', frame, lambda: True)
    messages = []
    for action in api.post_json.call_args_list:
        method, version, payload = action.args
        assert (method, version, payload['To'], payload['RoomId'], payload['Binary']) == ('SendRoomUnicast', '2023-07-20', 'bot', 'room', True)
        wire = base64.b64decode(payload['Message'])
        assert len(wire) < 64000 and wire[:4] == b'ctrl'
        assert int.from_bytes(wire[4:8], 'big') == len(wire) - 8
        messages.append(json.loads(wire[8:]))
    assert len(messages) == 3
    assert ''.join(m['ImageConfig']['Images'][0] for m in messages) == data
    assert all(not m['Message'] for m in messages[:-1])
    assert identity in messages[-1]['Message']
    assert messages[-1]['ImageConfig']['IsPartial'] is False
    assert [m['ImageConfig']['FragmentID'] for m in messages] == [1, 2, 3]
    sink.close()
    with pytest.raises(RuntimeError, match='结束'):
        sink.publish('call', frame, lambda: True)


def test_rtc_rejected_image_is_a_tool_failure_not_audio_teardown():
    api = Mock(); api.post_json.return_value = {'Result': {'Message': 'Rejected'}}
    session = SimpleNamespace(api=api, identity={'AppId': 'app', 'RoomId': 'room'}, bot='bot', started=True, closed=False)
    sink = VolcengineRtcScreen(session)
    frame = CapturedFrame(display_id='display', captured_at='now', width=100, height=100, image='data:image/jpeg;base64,YQ==')
    with pytest.raises(ValueError, match='未确认'):
        sink.publish('call', frame, lambda: True)
    assert not session.closed and not sink.closed


def test_rtc_image_receipt_does_not_trigger_a_text_only_visual_answer():
    async def run():
        api = Mock(); api.post_json.return_value = {'Result': 'ok'}
        session = VolcengineRtcSession(api, 'app', 'room', 'user', 'bot', '', VoiceSettings())
        session.started = True
        try:
            result = VoiceToolResult(status='completed', text='capture metadata', image_frame_id='frame')
            assert await session.deliver_tool_result('capture', result) == 'accepted'
            message = json.loads(api.post_json.call_args.args[2]['Message'])
            assert message['ToolCallID'] == 'capture'
            content = json.loads(message['Content'])
            assert content['status'] == 'running'
            assert 'frame' in content['text'] and '不要描述画面' in content['text']
            assert await session.deliver_tool_result('capture', result) == 'duplicate'
            assert api.post_json.call_count == 1
            await session.deliver_tool_result('edit', VoiceToolResult(status='completed', text='已修改草稿'))
            content = json.loads(json.loads(api.post_json.call_args.args[2]['Message'])['Content'])
            assert content['status'] == 'completed' and content['text'] == '已修改草稿'
        finally:
            await session.aclose()
    asyncio.run(run())
