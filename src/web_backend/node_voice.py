"""Node-bound voice call leases and asynchronous delegation to the existing runner."""
import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.config_loader import ConfigLoader
from src.providers.voice_registry import voice_provider
from src.providers.voice_provider import VoiceCall, RtcVoiceCall, VoiceProtocol, VoiceTaskUpdate
from src.providers.voice_control import VoiceControl
from src.voice_settings import node_voice_settings
from .node_memory_store import read_node_memory_text
from .node_config_service import node_config_service
from .node_voice_progress import voice_task_progress
from .node_request_tracking import find_completed_request
from .node_voice_records import VoiceFinish
from .node_voice_receipts import VoiceReceiptStore
from .shared import now_text


class VoiceOffer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sdp: str | None = Field(default=None, min_length=20, max_length=128_000)
    # Absence identifies an old page; it never selects a fallback protocol.
    protocols: list[VoiceProtocol] | None = Field(default=None, max_length=8)


class VoiceDelegation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    delegation_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=32_000)


class VoiceDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    stage: str = Field(max_length=120)
    event: Literal["connected", "error", "ended"]
    detail: str = Field(default="", max_length=1500)


@dataclass
class VoiceLease:
    node_id: str
    graph_id: str
    owner: str
    expires: float
    tasks: dict[str, tuple[str, str]] = field(default_factory=dict)
    results: dict[str, dict] = field(default_factory=dict)
    started_at: str = field(default_factory=now_text)
    finished: VoiceFinish | None = None
    call: VoiceCall | RtcVoiceCall | None = None
    delegation: bool = True

    def close(self):
        if self.call is not None and self.call.session is not None:
            self.call.session.close()


class NodeVoiceApi:
    def __init__(self, core):
        self.core = core
        self._lock = threading.RLock()
        self._leases: dict[str, VoiceLease] = {}
        self._receipts = VoiceReceiptStore(core.graph_runtime)

    def _owner(self, request):
        return self.core.access_api.message_access_metadata(request)["_access_client_id"]

    def _lease(self, session_id, node_id, graph_id, request):
        self.core.node_ops.require_node_visible(node_id, graph_id, request)
        owner = self._owner(request)
        now = time.monotonic()
        for key in list(self._leases):
            if self._leases[key].expires <= now:
                self._leases[key].close()
                del self._leases[key]
        lease = self._leases.get(session_id)
        if lease is None or (lease.node_id, lease.graph_id, lease.owner) != (node_id, graph_id, owner):
            raise HTTPException(404, "语音会话不存在或已结束。")
        return lease

    def _context(self, node_id, graph_id, request):
        cfg = self.core.node_ops.get_node_instance_config(node_id, graph_id, request=request)["node"]
        if cfg.get("type_id") != "agent_node":
            raise HTTPException(400, "语音通话仅适用于 Agent 节点。")
        settings = node_voice_settings(cfg)
        provider_id = settings.provider_id
        if not provider_id:
            raise HTTPException(400, "请先在节点的“语音设置”中选择语音 Provider。")
        config = ConfigLoader().get_provider_config(provider_id)
        runtime = self.core.graph_runtime
        history = read_node_memory_text(runtime._node_memory_path(node_id, graph_id),
                                        runtime._node_messages_path(node_id, graph_id), max_chars=12000)
        context = (f"节点：{cfg.get('name') or node_id}\n"
                   f"节点设定：{cfg.get('system_prompt', '')}\n"
                   f"最近历史（仅作背景，完整历史可向原节点查询）：\n{history}")
        return config, context, settings

    async def describe(self, node_id: str, request: Request, graph_id: str = "default"):
        graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        self.core.node_ops.require_node_visible(node_id, graph_id, request)
        try:
            config, _, settings = await asyncio.to_thread(self._context, node_id, graph_id, request)
            provider = voice_provider(config)
            provider.validate(settings)
            return {"transport": provider.transport, "protocol": provider.protocol}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    async def start(self, node_id: str, payload: VoiceOffer, request: Request, graph_id: str = "default"):
        graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        self.core.node_ops.require_node_visible(node_id, graph_id, request)
        owner = self._owner(request)
        try:
            config, context, settings = await asyncio.to_thread(self._context, node_id, graph_id, request)
            provider = voice_provider(config)
            provider.validate(settings)
            if payload.protocols is None or provider.protocol not in payload.protocols:
                raise HTTPException(409, "语音页面版本与服务不一致，请刷新当前页面后重新拨号；若仍出现，请更新该网址的前端。")
            if provider.transport == "webrtc":
                if payload.sdp is None or not payload.sdp.startswith("v=0") or "m=audio" not in payload.sdp:
                    raise HTTPException(400, "缺少有效的麦克风 WebRTC offer。")
            elif payload.sdp is not None:
                raise HTTPException(409, "语音供应商已切换，请重新拨号。")
            servers = self._ice_servers() if provider.server_media else ()
            answer = await provider.create_call(config, payload.sdp, context, settings, ice_servers=servers)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        session_id = uuid.uuid4().hex
        try:
            with self._lock:
                now = time.monotonic()
                for key in list(self._leases):
                    if self._leases[key].expires <= now:
                        self._leases.pop(key).close()
                lease = VoiceLease(node_id, graph_id, owner, now + 3600,
                                   call=answer, delegation=provider.delegation)
                self._receipts.register(node_id, graph_id, session_id, owner, lease.started_at,
                                        node_owned_dialogue=provider.node_owned_dialogue)
                self._leases[session_id] = lease
        except BaseException:
            if answer.session is not None:
                await answer.session.aclose()
            raise
        return {"session_id": session_id, **answer.connection(), "model": answer.model,
                "protocol": answer.protocol}

    async def control(self, node_id: str, session_id: str, payload: VoiceControl,
                      request: Request, graph_id: str = "default"):
        graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        with self._lock:
            lease = self._lease(session_id, node_id, graph_id, request)
            if lease.finished is not None or not isinstance(lease.call, RtcVoiceCall):
                raise HTTPException(409, "RTC 通话未开启或已经结束。")
            session = lease.call.session
        try:
            await session.control(payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

    def _ice_servers(self) -> tuple[dict, ...]:
        service = self.core.peer_api.service
        servers = [{"urls": url} for url in service.store.settings.stun_urls]
        if service.ice_lease is not None:
            service.ice_lease.require_fresh()
            servers.extend(server.model_dump() for server in service.ice_lease.ice_servers)
        return tuple(servers)

    async def close(self):
        with self._lock:
            calls = [lease.call for lease in self._leases.values() if lease.call is not None]
            self._leases.clear()
        await asyncio.gather(*(call.session.aclose() for call in calls if call.session is not None))

    def delegate(self, node_id: str, session_id: str, payload: VoiceDelegation,
                 request: Request, graph_id: str = "default"):
        graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        with self._lock:
            lease = self._lease(session_id, node_id, graph_id, request)
            if lease.finished is not None:
                raise HTTPException(409, "语音通话已结束。")
            if not lease.delegation:
                raise HTTPException(400, "此语音供应商不支持节点任务委派。")
            previous = lease.tasks.get(payload.delegation_id)
            if previous:
                if previous[1] != payload.text:
                    raise HTTPException(409, "同一个语音任务编号不能重复提交不同内容。")
                return {"request_id": previous[0], "duplicate": True}
            if len(lease.tasks) >= 200:
                raise HTTPException(409, "本次通话的任务数量已达上限，请重新开始通话。")
            if not payload.text.strip():
                raise HTTPException(400, "语音任务内容不能为空。")
            request_id = uuid.uuid4().hex
            self.core.node_ops.enqueue_node_instance_pending(node_id, {
                "payload": payload.text, "trace_id": request_id,
                "source": "voice_call", "idempotency_key": f"voice:{session_id}:{payload.delegation_id}",
            }, graph_id, request)
            lease.tasks[payload.delegation_id] = (request_id, payload.text)
            return {"request_id": request_id, "duplicate": False}

    def task(self, node_id: str, session_id: str, request_id: str,
             request: Request, graph_id: str = "default"):
        graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        with self._lock:
            lease = self._lease(session_id, node_id, graph_id, request)
            if request_id not in {item[0] for item in lease.tasks.values()}:
                raise HTTPException(404, "语音任务不存在。")
            if request_id in lease.results:
                return lease.results[request_id]
            path = self.core.graph_runtime._node_config_path(node_id, graph_id)
            cfg = node_config_service.read_strict(path)
            completed = find_completed_request(cfg, request_id)
            if completed:
                result = {"status": "failed" if completed["role"] == "system" else "completed",
                          "text": completed["message"]}
                lease.results[request_id] = result
                return result
            live = self.core.node_live_outputs.get(graph_id, node_id)
            if live.get("trace_id") == request_id:
                return {"status": "running", "text": voice_task_progress(live)}
            pending = cfg.get("pending") or []
            inflight = cfg.get("inflight") or {}
            if inflight.get("trace_id") == request_id:
                return {"status": "running", "text": ""}
            if any(item.get("trace_id") == request_id for item in pending):
                return {"status": "queued", "text": ""}
            # Cancellation clears pending/inflight without always writing a completion record.
            return {"status": "cancelled", "text": "任务已不在执行队列中，未取得完成结果；不能视为成功。"}

    def diagnostic(self, node_id: str, session_id: str, payload: VoiceDiagnostic,
                   request: Request, graph_id: str = "default"):
        graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        with self._lock:
            self._lease(session_id, node_id, graph_id, request)
            self.core.graph_runtime._log_graph_event(
                graph_id, "voice_connection", node_id=node_id, voice_session_id=session_id,
                stage=payload.stage, status=payload.event, detail=payload.detail,
            )
        return {"ok": True}

    async def deliver_update(self, node_id: str, session_id: str, request_id: str,
                    request: Request, graph_id: str = "default"):
        """Read the authorized task state ourselves; clients cannot invent task progress."""
        graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        with self._lock:
            lease = self._lease(session_id, node_id, graph_id, request)
            if lease.finished is not None:
                raise HTTPException(409, "语音通话已结束。")
            if lease.call is None or lease.call.session is None:
                raise HTTPException(400, "此语音供应商通过客户端返回任务结果。")
            delegation_id = next((key for key, value in lease.tasks.items() if value[0] == request_id), None)
            if delegation_id is None:
                raise HTTPException(404, "语音任务不存在。")
            session = lease.call.session
        result = await asyncio.to_thread(self.task, node_id, session_id, request_id, request, graph_id)
        try:
            status = await session.deliver_update(delegation_id, VoiceTaskUpdate(task_id=request_id, **result))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {**result, "delivery": status}

    def finish(self, node_id: str, session_id: str, payload: VoiceFinish,
               request: Request, graph_id: str = "default"):
        graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        self.core.node_ops.require_node_visible(node_id, graph_id, request)
        owner = self._owner(request)
        with self._lock:
            record_id = self._receipts.finish(node_id, graph_id, session_id, owner, payload)
            lease = self._leases.get(session_id)
            if lease is not None:
                lease.finished = payload
                lease.expires = time.monotonic() + 3600
                lease.close()
            self.core.graph_runtime._log_graph_event(
                graph_id, "node_voice_recorded", node_id=node_id, record_id=record_id,
            )
            return {"ok": True, "record_id": record_id}

    def end(self, node_id: str, session_id: str, request: Request, graph_id: str = "default"):
        graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        with self._lock:
            lease = self._lease(session_id, node_id, graph_id, request)
            self._receipts.abandon(node_id, graph_id, session_id, lease.owner)
            lease.close()
            del self._leases[session_id]
        return {"ok": True}
