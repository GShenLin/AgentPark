"""Owned AI RTC task: activation after room join, vision control and node feedback."""
import asyncio
import json
import logging
import time
import uuid

from .voice_provider import VoiceSession, VoiceTaskUpdate, VoiceProvider
from .voice_control import VoiceControl
from .voice_tools import VoiceToolResult

log = logging.getLogger(__name__)
VERSION = "2025-06-01"


class VolcengineRtcSession(VoiceSession):
    def __init__(self, api, app_id, room, user, bot, context, settings):
        self.api = api
        self.identity = {"AppId": app_id, "RoomId": room, "TaskId": uuid.uuid4().hex}
        self.user, self.bot, self.context, self.settings = user, bot, context, settings
        self.loop = asyncio.get_running_loop()
        self.lock = asyncio.Lock()
        self.started = False
        self.closed = False
        self.deadline = time.monotonic() + 60
        self.absolute_deadline = time.monotonic() + 3550
        self.last_updates: dict[str, VoiceTaskUpdate] = {}
        self.last_progress: dict[str, float] = {}
        self.closing: asyncio.Task | None = None
        self.watchdog = asyncio.create_task(self._watch())

    async def _request(self, action, **payload):
        result = await asyncio.to_thread(self.api.post_json, action, VERSION, {**self.identity, **payload})
        if result.get("Result") != "ok":
            raise ValueError(f"火山 {action} 未确认操作成功。")

    def _configuration(self):
        return {
            "ASRConfig": {"Provider": "volcano", "ProviderParams": {
                "Mode": "bigmodel", "Credential": {"ApiResourceId": "volc.seedasr.sauc.duration"}, "StreamMode": 2}},
            "LLMConfig": {
                "Mode": "ArkV3", "ModelName": self.settings.model, "ThinkingType": "disabled",
                "SystemMessages": [VoiceProvider.instructions(self.context)],
                "Tools": [{"type": "function", "function": {key: value for key, value in tool.items() if key != "type"}}
                          for tool in VoiceProvider.tools()],
                "EnableToolCallHistory": True,
                "VisionConfig": {"Enable": True, "SnapshotConfig": {
                    "StreamType": 1, "Interval": 100, "ImagesLimit": 5}},
            },
            "TTSConfig": {"Provider": "volcano_bidirection", "ProviderParams": {
                "Credential": {"ResourceId": "seed-tts-2.0"},
                "VolcanoTTSParameters": json.dumps({"req_params": {"speaker": self.settings.voice}})}},
            "SubtitleConfig": {"SubtitleMode": 1},
        }

    async def control(self, command: VoiceControl):
        async with self.lock:
            if self.closed:
                raise ValueError("火山语音会话已结束。")
            self.deadline = min(time.monotonic() + 60, self.absolute_deadline)
            if command.action == "activate":
                if not self.started:
                    # Mark before submitting: even an ambiguous timeout must attempt StopVoiceChat.
                    self.started = True
                    try:
                        await self._request("StartVoiceChat", Config=self._configuration(),
                                            AgentConfig={"TargetUserId": [self.user], "UserId": self.bot})
                    except BaseException:
                        self.close()
                        raise
            elif command.action != "heartbeat":
                raise ValueError("不支持的 RTC 控制指令。")

    async def deliver_tool_result(self, call_id: str, result: VoiceToolResult):
        if result.status == 'completed' and result.image_frame_id is not None:
            # RTC queues the image prompt until the pending function turn ends.
            # A capture receipt must not ask that earlier, text-only turn to see
            # pixels it has not received yet. The image prompt answers afterward.
            return await self.deliver_update(call_id, VoiceTaskUpdate(task_id=call_id, status='running', text=(
                '截图已经截取，图像正在通过独立图片消息进入视觉上下文。当前这份回执没有图像内容，'
                '不要描述画面或猜测数字、颜色、形状。请只简短确认正在查看，'
                '图片消息会在本轮结束后触发实际读图回复，无需再调用工具。'
                f' frame_id={result.image_frame_id}')))
        return await super().deliver_tool_result(call_id, result)

    async def deliver_update(self, delegation_id: str, result: VoiceTaskUpdate):
        async with self.lock:
            if self.closed or not self.started:
                raise ValueError("火山语音会话尚未启动或已经结束。")
            previous = self.last_updates.get(delegation_id)
            if result == previous:
                return "duplicate"
            text = result.text[:8000]
            if len(result.text) > 8000:
                text += "\n（结果过长，此处为前 8000 字符；完整结果已保存在原节点。）"
            content = json.dumps({"task_id": result.task_id, "status": result.status, "text": text}, ensure_ascii=False)
            if previous is None:
                await self._request("UpdateVoiceChat", Command="function", Message=json.dumps({
                    "ToolCallID": delegation_id, "Content": content}, ensure_ascii=False))
            else:
                if result.status in {"queued", "running"}:
                    delay = 10 - (time.monotonic() - self.last_progress.get(delegation_id, 0))
                    if delay > 0:
                        await asyncio.sleep(delay)
                    if self.closed:
                        raise ValueError("火山语音会话已结束。")
                await self._request("UpdateVoiceChat", Command="ExternalTextToLLM", InterruptMode=2,
                    Message="原节点后台任务的真实状态更新。请简短转述给用户，不能因此再次提交任务：\n" + content)
            self.last_updates[delegation_id] = result
            self.last_progress[delegation_id] = time.monotonic()
            return "accepted"

    async def _watch(self):
        try:
            while not self.closed:
                await asyncio.sleep(10)
                if time.monotonic() >= self.deadline:
                    self.close()
        except asyncio.CancelledError:
            return

    def close(self):
        self.loop.call_soon_threadsafe(self._begin_close)

    def _begin_close(self):
        if self.closing is None:
            self.closed = True
            self.watchdog.cancel()
            self.closing = asyncio.create_task(self._stop())
            self.closing.add_done_callback(self._report_close)

    @staticmethod
    def _report_close(task):
        if not task.cancelled() and task.exception() is not None:
            error = task.exception()
            log.error("停止火山 RTC 任务失败", exc_info=(type(error), error, error.__traceback__))

    async def _stop(self):
        async with self.lock:
            if self.started:
                for attempt in range(3):
                    try:
                        await self._request("StopVoiceChat")
                        self.started = False
                        return
                    except ValueError:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(1 + attempt)

    async def aclose(self):
        self._begin_close()
        await asyncio.shield(self.closing)
