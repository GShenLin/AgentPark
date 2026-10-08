"""Native proactive speech, coalesced per task and scheduled between user turns."""
from collections import OrderedDict
from dataclasses import dataclass
import time

from .voice_provider import VoiceTaskUpdate


TERMINAL = {"completed", "failed", "cancelled"}


def notification_text(update: VoiceTaskUpdate) -> str:
    if update.status == "running" and update.text:
        return "后台任务进展：" + update.text
    labels = {"queued": "后台任务已排队", "running": "后台任务正在执行",
              "completed": "后台任务已完成", "failed": "后台任务失败", "cancelled": "后台任务已取消"}
    return labels[update.status] + "。" + update.text


@dataclass
class Notification:
    update: VoiceTaskUpdate
    response_id: str = ""
    interrupted: bool = False


class DoubaoVoiceNotifications:
    # An explicit speech cadence: retain the latest progress, never a growing backlog.
    progress_interval = 10.0

    def __init__(self, send, emit, audio):
        self.send, self.emit, self.audio = send, emit, audio
        self.pending: OrderedDict[str, VoiceTaskUpdate] = OrderedDict()
        self.inflight: Notification | None = None
        self.last_progress_at = 0.0

    def enqueue(self, update: VoiceTaskUpdate):
        self.pending[update.task_id] = update

    def clear_progress(self, task_id: str):
        self.pending.pop(task_id, None)

    def interrupt(self):
        if self.inflight is not None:
            self.inflight.interrupted = True

    def audio_started(self, event):
        item = self.inflight
        if item is None:
            return
        if event.get("tts_type") != "chat_tts_text":
            if item.interrupted:
                self.inflight = None
            return
        item.response_id = event["response_id"]
        if not item.interrupted:
            self._caption(item, False)

    def audio_done(self, response_id):
        item = self.inflight
        if item is not None and item.response_id == response_id:
            if not item.interrupted:
                self._caption(item, True)
            self.inflight = None

    def _caption(self, item, done):
        # SayHello produces audio without output_text events. Persist its supplied text
        # only when the provider starts/finishes that synthesis, never on enqueue.
        self.emit({"type": "transcript", "role": "assistant", "text": notification_text(item.update),
                   "done": done, "replace": True})

    async def flush(self, *, busy: bool):
        if busy or self.inflight is not None or self.audio.buffer or not self.pending:
            return
        now = time.monotonic()
        selected = next((key for key, update in self.pending.items() if update.status in TERMINAL), None)
        if selected is None:
            if now - self.last_progress_at < self.progress_interval:
                return
            selected = next(iter(self.pending))
        update = self.pending.pop(selected)
        self.inflight = Notification(update)
        await self.send({"type": "speech_text_buffer.commit", "text": notification_text(update)})
        if update.status not in TERMINAL:
            self.last_progress_at = now
