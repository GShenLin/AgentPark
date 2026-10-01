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
from src.providers.codex_voice import create_codex_voice_call
from .node_memory_store import read_node_memory_text
from .node_config_service import node_config_service
from .node_request_tracking import find_completed_request


class VoiceOffer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sdp: str = Field(min_length=20, max_length=128_000)
    conference: bool = False


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


class NodeVoiceApi:
    def __init__(self, core):
        self.core = core
        self._lock = threading.RLock()
        self._leases: dict[str, VoiceLease] = {}

    def _owner(self, request):
        return self.core.access_api.message_access_metadata(request)["_access_client_id"]

    def _lease(self, session_id, node_id, graph_id, request):
        self.core.node_ops.require_node_visible(node_id, graph_id, request)
        owner = self._owner(request)
        now = time.monotonic()
        for key in list(self._leases):
            if self._leases[key].expires <= now:
                del self._leases[key]
        lease = self._leases.get(session_id)
        if lease is None or (lease.node_id, lease.graph_id, lease.owner) != (node_id, graph_id, owner):
            raise HTTPException(404, "语音会话不存在或已结束。")
        return lease

    def _context(self, node_id, graph_id, request):
        cfg = self.core.node_ops.get_node_instance_config(node_id, graph_id, request=request)["node"]
        if cfg.get("type_id") != "agent_node":
            raise HTTPException(400, "语音通话仅适用于 Agent 节点。")
        provider_id = str(cfg.get("provider_id") or "").strip()
        if not provider_id:
            raise HTTPException(400, "请先为节点选择 GPT_Official 等 Codex 登录 Provider。")
        config = ConfigLoader().get_provider_config(provider_id)
        runtime = self.core.graph_runtime
        history = read_node_memory_text(
            runtime._node_memory_path(node_id, graph_id), runtime._node_messages_path(node_id, graph_id),
            max_chars=12_000,
        )
        context = f"节点：{cfg.get('name') or node_id}\nProvider：{provider_id}\n最近历史（仅作背景）：\n{history}"
        return config, context

    async def start(self, node_id: str, payload: VoiceOffer, request: Request, graph_id: str = "default"):
        graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        self.core.node_ops.require_node_visible(node_id, graph_id, request)
        owner = self._owner(request)
        if not payload.sdp.startswith("v=0") or "m=audio" not in payload.sdp:
            raise HTTPException(400, "缺少有效的麦克风 WebRTC offer。")
        try:
            config, context = await asyncio.to_thread(self._context, node_id, graph_id, request)
            if payload.conference:
                context += (
                    "\n通话模式：多人语音。输入音频包含用户和其他节点的实时发言。"
                    "你仍代表上面指定的节点，发言时先简短报自己的节点名称，便于其他参与者辨认。"
                    "根据自己的判断决定是否回应或委派自己的后端执行工具，无主持人安排发言。"
                    "区分用户、其他节点与你自己的发言；其他节点的执行结果不等于你已执行。"
                )
            answer = await create_codex_voice_call(config, payload.sdp, context)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        session_id = uuid.uuid4().hex
        with self._lock:
            now = time.monotonic()
            self._leases = {k: v for k, v in self._leases.items() if v.expires > now}
            self._leases[session_id] = VoiceLease(node_id, graph_id, owner, now + 3600)
        return {"session_id": session_id, "sdp": answer.sdp, "model": answer.model}

    def delegate(self, node_id: str, session_id: str, payload: VoiceDelegation,
                 request: Request, graph_id: str = "default"):
        graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        with self._lock:
            lease = self._lease(session_id, node_id, graph_id, request)
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
                return {"status": "running", "text": ""}
            pending = cfg.get("pending") or []
            inflight = cfg.get("inflight") or {}
            if any(item.get("trace_id") == request_id for item in pending) or inflight.get("trace_id") == request_id:
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

    def end(self, node_id: str, session_id: str, request: Request, graph_id: str = "default"):
        graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        with self._lock:
            self._lease(session_id, node_id, graph_id, request)
            del self._leases[session_id]
        return {"ok": True}
