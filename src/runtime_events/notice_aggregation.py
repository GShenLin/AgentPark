from __future__ import annotations

from dataclasses import dataclass
import json
import threading
from typing import Any

from .event_models import RuntimeEventEnvelope


MAX_STAGES_PER_TRACE = 64
MAX_NOTICE_MESSAGE_CHARS = 1200


@dataclass
class NoticeStageState:
    stage: str
    source: str
    provider: str
    latest_message: str
    total_count: int = 1
    state_change_count: int = 1
    repeat_count: int = 0


@dataclass
class NoticeTraceState:
    total_count: int
    stages: dict[str, NoticeStageState]
    overflow_stage_count: int = 0
    overflow_notice_count: int = 0


class RuntimeNoticeContextAggregator:
    """Aggregates high-frequency runtime notices while raw events remain in the audit log."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, str, str], NoticeTraceState] = {}
        self._lock = threading.Lock()

    def record(self, envelope: RuntimeEventEnvelope) -> tuple[str, str]:
        payload = envelope.payload
        trace_key = str(envelope.trace_id or "untraced")
        key = (envelope.source_graph_id, envelope.source_node_id, trace_key)
        stage = str(payload.get("stage") or "unspecified").strip() or "unspecified"
        message = str(payload.get("message") or "").strip()
        if len(message) > MAX_NOTICE_MESSAGE_CHARS:
            message = message[:MAX_NOTICE_MESSAGE_CHARS] + "...[truncated]"
        source = str(payload.get("source") or "").strip()
        provider = str(payload.get("provider") or "").strip()

        with self._lock:
            state = self._states.setdefault(key, NoticeTraceState(total_count=0, stages={}))
            state.total_count += 1
            stage_state = state.stages.get(stage)
            if stage_state is None:
                if len(state.stages) >= MAX_STAGES_PER_TRACE:
                    state.overflow_stage_count += 1
                    state.overflow_notice_count += 1
                else:
                    state.stages[stage] = NoticeStageState(
                        stage=stage,
                        source=source,
                        provider=provider,
                        latest_message=message,
                    )
            else:
                stage_state.total_count += 1
                if (
                    stage_state.latest_message == message
                    and stage_state.source == source
                    and stage_state.provider == provider
                ):
                    stage_state.repeat_count += 1
                else:
                    stage_state.state_change_count += 1
                    stage_state.latest_message = message
                    stage_state.source = source
                    stage_state.provider = provider
            return self._aggregation_key(key), self._render(key, state)

    def clear_node(self, graph_id: str, node_id: str) -> None:
        with self._lock:
            keys = [key for key in self._states if key[0] == graph_id and key[1] == node_id]
            for key in keys:
                self._states.pop(key, None)

    @staticmethod
    def _aggregation_key(key: tuple[str, str, str]) -> str:
        return "runtime_notice:" + ":".join(key)

    @staticmethod
    def _render(key: tuple[str, str, str], state: NoticeTraceState) -> str:
        payload: dict[str, Any] = {
            "kind": "runtime_notice_summary",
            "graph_id": key[0],
            "node_id": key[1],
            "trace_id": key[2],
            "total_notice_count": state.total_count,
            "stages": [
                {
                    "stage": item.stage,
                    "source": item.source,
                    "provider": item.provider,
                    "total_count": item.total_count,
                    "state_change_count": item.state_change_count,
                    "repeat_count": item.repeat_count,
                    "latest_message": item.latest_message,
                }
                for item in state.stages.values()
            ],
        }
        if state.overflow_stage_count:
            payload["overflow_stage_count"] = state.overflow_stage_count
            payload["overflow_notice_count"] = state.overflow_notice_count
        return "Runtime notice state summary:\n" + json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
