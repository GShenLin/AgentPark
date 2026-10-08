import asyncio
import base64
import json
from unittest.mock import AsyncMock

import pytest

from src.providers.doubao_node_voice import DoubaoNodeVoice
from src.providers.voice_audio import PcmOutputTrack
from src.providers.voice_provider import VoiceTaskUpdate


@pytest.fixture
def dialogue():
    events, sender, audio = [], AsyncMock(), PcmOutputTrack()
    yield DoubaoNodeVoice(sender, events.append, audio), events, sender, audio
    audio.stop()


def tool(call_id="call1", text="请读取文件"):
    return {"call_id": call_id, "name": "delegate_to_node", "arguments": json.dumps({"text": text})}


def delegate(router, *items):
    router.receive({"type": "response.function_call_arguments.done", "items": list(items)})


def test_native_chat_and_final_asr_do_not_enqueue_tasks(dialogue):
    router, events, sender, audio = dialogue
    for kind, payload in [("started", {}), ("delta", {"delta": "你好"}), ("completed", {"text": "你好。"})]:
        router.receive({"type": "conversation.item.input_audio_transcription." + kind, "item_id": "q1", **payload})
    router.receive({"type": "response.output_text.delta", "response_id": "r1", "delta": "你好呀"})
    router.receive({"type": "response.output_text.done", "response_id": "r1", "text": "你好呀！"})
    router.receive({"type": "response.output_audio.started", "response_id": "r1"})
    pcm = b"\x00\x10" * 100
    router.receive({"type": "response.output_audio.delta", "delta": base64.b64encode(pcm).decode()})
    assert audio.buffer.read(len(pcm)) == pcm
    assert not router.calls
    assert not [e for e in events if e["type"] == "delegation"]
    assert events[-1]["text"] == "你好呀！" and events[-1]["done"]
    sender.assert_not_called()


def test_native_tool_results_are_correlated_and_returned_once(dialogue):
    router, events, sender, _ = dialogue
    delegate(router, tool())
    delegate(router, tool())
    assert events == [{"type": "delegation", "id": "call1", "text": "请读取文件"}]
    result = VoiceTaskUpdate(task_id="task1", status="completed", text="文件内容：蓝色风铃")
    assert asyncio.run(router.deliver_update("call1", result)) == "accepted"
    payload = sender.call_args.args[0]
    assert payload["type"] == "conversation.item.create"
    assert payload["items"][0]["call_id"] == "call1"
    assert payload["items"][0]["role"] == "tool"
    assert json.loads(payload["items"][0]["content"][0]["text"]) == result.model_dump()
    assert asyncio.run(router.deliver_update("call1", result)) == "duplicate"
    assert sender.call_count == 1
    with pytest.raises(ValueError, match="不同结果"):
        asyncio.run(router.deliver_update("call1", VoiceTaskUpdate(task_id="task1", status="failed", text="failed")))


def test_parallel_calls_return_one_complete_batch_in_original_order(dialogue):
    router, _, sender, _ = dialogue
    delegate(router, tool("a"), tool("b", "查资料"))
    failed = VoiceTaskUpdate(task_id="task1", status="failed", text="权限不足")
    asyncio.run(router.deliver_update("b", failed))
    sender.assert_not_called()
    asyncio.run(router.deliver_update("a", VoiceTaskUpdate(task_id="task1", status="cancelled", text="")))
    items = sender.call_args.args[0]["items"]
    assert [i["call_id"] for i in items] == ["a", "b"]
    assert json.loads(items[1]["content"][0]["text"]) == failed.model_dump()


def test_barge_in_stops_old_audio_but_preserves_late_tool_results(dialogue):
    router, _, sender, audio = dialogue
    delegate(router, tool())
    event = {"type": "response.output_audio.delta", "delta": base64.b64encode(b"\x00\x10" * 100).decode()}
    router.receive({"type": "response.output_audio.started", "response_id": "old"})
    router.receive(event)
    router.receive({"type": "conversation.item.input_audio_transcription.started", "item_id": "new"})
    router.receive(event)
    assert not audio.buffer
    asyncio.run(router.deliver_update("call1", VoiceTaskUpdate(task_id="task1", status="completed", text="晚到的真实结果")))
    assert sender.call_args.args[0]["items"][0]["call_id"] == "call1"
    router.receive({"type": "response.output_audio.started", "response_id": "new"})
    router.receive(event)
    assert audio.buffer


@pytest.mark.parametrize("invalid", [
    {**tool(), "name": "unregistered"}, {**tool(), "arguments": '{"text": 12}'},
    {**tool(), "arguments": '{"text":" ","extra":true}'}, {**tool(), "call_id": ""},
])
def test_invalid_batch_never_partially_executes(dialogue, invalid):
    router, events, _, _ = dialogue
    with pytest.raises(ValueError):
        delegate(router, tool("valid"), invalid)
    assert not events and not router.calls


def test_conflicting_calls_and_unknown_results_fail(dialogue):
    router, _, sender, _ = dialogue
    delegate(router, tool())
    with pytest.raises(ValueError, match="不同参数"):
        delegate(router, tool(text="不同任务"))
    with pytest.raises(ValueError, match="已发出"):
        asyncio.run(router.deliver_update("unknown", VoiceTaskUpdate(task_id="task1", status="completed", text="fake")))
    sender.assert_not_called()


def test_submission_ack_releases_chat_then_real_progress_and_completion_notify(dialogue):
    router, events, sender, audio = dialogue
    delegate(router, tool())
    queued = VoiceTaskUpdate(task_id="background", status="queued", text="")
    asyncio.run(router.deliver_update("call1", queued))
    assert json.loads(sender.call_args.args[0]["items"][0]["content"][0]["text"])["status"] == "queued"
    assert router.calls["call1"].acknowledged
    router.receive({"type": "response.output_audio.done", "response_id": "ack"})
    router.receive({"type": "conversation.item.input_audio_transcription.started", "item_id": "chat"})
    progress = VoiceTaskUpdate(task_id="background", status="running", text="正在读取验证文件")
    asyncio.run(router.deliver_update("call1", progress))
    asyncio.run(router.flush_notifications())
    assert sender.call_count == 1  # Never talk over the user.
    router.receive({"type": "conversation.item.input_audio_transcription.completed", "text": "你好"})
    router.receive({"type": "response.output_text.done", "response_id": "chat", "text": "你好呀"})
    router.receive({"type": "response.output_audio.done", "response_id": "chat"})
    asyncio.run(router.flush_notifications())
    assert sender.call_args.args[0] == {"type": "speech_text_buffer.commit", "text": "后台任务进展：正在读取验证文件"}
    router.receive({"type": "response.output_audio.started", "response_id": "notice", "tts_type": "chat_tts_text"})
    router.receive({"type": "response.output_audio.done", "response_id": "notice"})
    assert events[-1]["text"] == "后台任务进展：正在读取验证文件" and events[-1]["done"]
    done = VoiceTaskUpdate(task_id="background", status="completed", text="真实文件内容")
    asyncio.run(router.deliver_update("call1", done))
    audio.append(b"\x00\x10" * 40)
    asyncio.run(router.flush_notifications())
    assert sender.call_count == 2  # Wait for PCM already queued for playback.
    audio.interrupt()
    asyncio.run(router.flush_notifications())
    assert sender.call_args.args[0]["text"] == "后台任务已完成。真实文件内容"
    assert asyncio.run(router.deliver_update("call1", done)) == "duplicate"


def test_progress_coalesces_and_terminal_supersedes_unsaid_progress(dialogue):
    router, _, sender, _ = dialogue
    delegate(router, tool())
    asyncio.run(router.deliver_update("call1", VoiceTaskUpdate(task_id="t", status="queued", text="")))
    for text in ["读取文件", "运行验证", "整理结果"]:
        asyncio.run(router.deliver_update("call1", VoiceTaskUpdate(task_id="t", status="running", text=text)))
    assert len(router.notifications.pending) == 1
    asyncio.run(router.deliver_update("call1", VoiceTaskUpdate(task_id="t", status="failed", text="验证未通过")))
    router.receive({"type": "response.output_audio.done", "response_id": "ack"})
    asyncio.run(router.flush_notifications())
    assert sender.call_args.args[0]["text"] == "后台任务失败。验证未通过"


def test_interrupted_notification_does_not_write_a_completed_caption(dialogue):
    router, events, _, _ = dialogue
    update = VoiceTaskUpdate(task_id="t", status="completed", text="结果")
    router.notifications.enqueue(update)
    asyncio.run(router.flush_notifications())
    router.receive({"type": "response.output_audio.started", "response_id": "notice", "tts_type": "chat_tts_text"})
    router.receive({"type": "conversation.item.input_audio_transcription.started", "item_id": "chat"})
    router.receive({"type": "response.output_audio.done", "response_id": "notice"})
    assert not any(e.get("done") for e in events)
    assert router.notifications.inflight is None


def test_finished_activity_withdraws_unsaid_progress_without_a_redundant_notice(dialogue):
    router, _, sender, _ = dialogue
    delegate(router, tool())
    asyncio.run(router.deliver_update("call1", VoiceTaskUpdate(task_id="t", status="running", text="")))
    asyncio.run(router.deliver_update("call1", VoiceTaskUpdate(task_id="t", status="running", text="正在读取文件")))
    assert router.notifications.pending
    asyncio.run(router.deliver_update("call1", VoiceTaskUpdate(task_id="t", status="running", text="")))
    router.receive({"type": "response.output_audio.done", "response_id": "ack"})
    asyncio.run(router.flush_notifications())
    assert not router.notifications.pending and sender.call_count == 1
