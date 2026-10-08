"""Native Doubao dialogue events and correlated, batched node tool results."""
import asyncio
import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from .doubao_voice_notifications import DoubaoVoiceNotifications, TERMINAL
from .voice_audio import PcmOutputTrack
from .voice_provider import VoiceDelivery, VoiceTaskUpdate


class NodeTaskArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=32_000)


NODE_TOOL = {
    "type": "function", "name": "delegate_to_node",
    "description": "让当前原节点使用自己的主模型、完整历史、工具和权限执行任务，包括查资料、读写文件、写代码、查询或停止任务。此工具只提交后台任务，立即返回任务编号和排队或执行状态，进展和结果随后主动通知。不要为等待结果重复提交任务；普通聊天无需调用。",
    "parameters": NodeTaskArguments.model_json_schema(),
}


@dataclass
class NodeCall:
    text: str
    batch: tuple[str, ...]
    update: VoiceTaskUpdate | None = None
    acknowledged: bool = False


def transcript(role: str, text: str, done: bool, *, replace: bool = False) -> dict:
    return {"type": "transcript", "role": role, "text": text, "done": done, "replace": replace}


class DoubaoNodeVoice:
    def __init__(self, send: Callable[[dict], Awaitable[None]],
                 emit: Callable[[dict], None], audio: PcmOutputTrack):
        self.send, self.emit, self.audio = send, emit, audio
        self.calls: dict[str, NodeCall] = {}
        self.lock = asyncio.Lock()
        self.blocked_responses: set[str] = set()
        self.active_responses: set[str] = set()
        self.audio_response: str | None = None
        self.user_speaking = False
        self.response_pending = False
        self.notifications = DoubaoVoiceNotifications(send, emit, audio)

    @staticmethod
    def _text(event: dict, key: str) -> str:
        value = event.get(key)
        if not isinstance(value, str):
            raise ValueError(f"豆包语音事件缺少有效的 {key}。")
        return value

    def receive(self, event: dict) -> None:
        kind = self._text(event, "type")
        if kind in {"conversation.item.input_audio_transcription.started", "response.canceled"}:
            self.user_speaking = kind.endswith("transcription.started")
            self.response_pending = False
            self.notifications.interrupt()
            self.blocked_responses.update(self.active_responses)
            self.active_responses.clear()
            self.audio.interrupt()
            self.emit({"type": "interrupted"})
        elif kind == "conversation.item.input_audio_transcription.failed":
            raise ValueError("豆包语音识别失败。")
        elif kind == "conversation.item.input_audio_transcription.delta":
            # This endpoint sends cumulative ASR hypotheses, not token deltas.
            self.emit(transcript("user", self._text(event, "delta"), False, replace=True))
        elif kind == "conversation.item.input_audio_transcription.completed":
            self.user_speaking = False
            self.response_pending = True
            self.emit(transcript("user", self._text(event, "text"), True, replace=True))
        elif kind == "response.function_call_arguments.done":
            self.response_pending = False
            self._delegate(event)
        elif kind == "response.output_audio.delta":
            # Audio chunks have no response_id; ordered started/done events own them.
            if self.audio_response is None:
                raise ValueError("豆包音频分片缺少对应的开始事件。")
            if self.audio_response not in self.blocked_responses:
                pcm = base64.b64decode(self._text(event, "delta"), validate=True)
                self.audio.append(pcm)
        elif kind in {"response.output_text.delta", "response.output_text.done",
                      "response.output_audio.started",
                      "response.output_audio.done"}:
            response = self._text(event, "response_id")
            if not response:
                raise ValueError("豆包回复缺少 response_id。")
            if kind == "response.output_audio.started":
                self.audio_response = response
                self.notifications.audio_started(event)
            elif kind == "response.output_audio.done":
                self.audio_response = None
                self.notifications.audio_done(response)
                if response not in self.blocked_responses:
                    self.response_pending = False
            if response in self.blocked_responses:
                return
            self.active_responses.add(response)
            if kind == "response.output_text.delta":
                self.emit(transcript("assistant", self._text(event, "delta"), False))
            elif kind == "response.output_text.done":
                self.emit(transcript("assistant", self._text(event, "text"), True, replace=True))
        # Session/context acknowledgements and usage events require no UI action.

    def _delegate(self, event: dict) -> None:
        items = event.get("items")
        if not isinstance(items, list) or not items or len(items) > 200:
            raise ValueError("豆包工具调用缺少有效的 items。")
        parsed: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict) or item.get("name") != "delegate_to_node":
                raise ValueError("豆包请求了未注册的工具。")
            call_id = self._text(item, "call_id")
            if not call_id or len(call_id) > 200 or call_id in parsed:
                raise ValueError("豆包工具调用编号无效或重复。")
            args = NodeTaskArguments.model_validate_json(self._text(item, "arguments"))
            if not args.text.strip():
                raise ValueError("豆包工具任务不能为空。")
            parsed[call_id] = args.text
        batch = tuple(parsed)
        for call_id, text in parsed.items():
            old = self.calls.get(call_id)
            if old is not None and (old.text != text or old.batch != batch):
                raise ValueError("同一豆包工具调用收到了不同参数或批次。")
        if len(self.calls.keys() | parsed.keys()) > 200:
            raise ValueError("本次语音通话已达到 200 个工具调用，请重新拨号。")
        for call_id, text in parsed.items():
            if call_id not in self.calls:
                self.calls[call_id] = NodeCall(text, batch)
                self.emit({"type": "delegation", "id": call_id, "text": text})

    async def deliver_update(self, delegation_id: str, update: VoiceTaskUpdate) -> VoiceDelivery:
        async with self.lock:
            call = self.calls.get(delegation_id)
            if call is None:
                raise ValueError("节点状态不属于已发出的豆包工具调用。")
            previous = call.update
            if previous == update:
                return "duplicate"
            if previous is not None:
                if previous.task_id != update.task_id:
                    raise ValueError("同一工具调用不能改绑后台任务。")
                if previous.status in TERMINAL:
                    raise ValueError("已结束的语音任务不能返回不同结果。")
                if previous.status == "running" and update.status == "queued":
                    raise ValueError("执行中的任务不能退回排队状态。")
            call.update = update
            if call.acknowledged:
                # A disappearing activity is not a new spoken milestone; remove
                # any unsaid progress that would now describe an outdated operation.
                if update.status == "running" and previous.status == "running" and not update.text:
                    self.notifications.clear_progress(update.task_id)
                else:
                    # The submission tool has already returned. Send subsequent
                    # events through the provider's proactive speech/context channel.
                    self.notifications.enqueue(update)
            elif all(self.calls[key].update is not None for key in call.batch):
                # Complete the short submission tool, not the entire background job.
                await self.send({"type": "conversation.item.create", "items": [
                    {"call_id": key, "role": "tool", "content": [{
                        "type": "input_text", "text": self.calls[key].update.model_dump_json()}]}
                    for key in call.batch]})
                for key in call.batch:
                    self.calls[key].acknowledged = True
                self.response_pending = True
            return "accepted"

    async def flush_notifications(self):
        await self.notifications.flush(busy=(self.user_speaking or self.response_pending
                                             or any(not call.acknowledged for call in self.calls.values())))
