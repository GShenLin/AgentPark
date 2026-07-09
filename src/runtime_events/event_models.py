from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EVENTS = {"OnInput", "ToolFailure", "RuntimeNotice", "NetError", "WorkPersisted", "WorkFailed"}
ACTIONS = {"context.produce", "notice.write", "node.dispatch"}
TTLS = {"current_run", "next_turn", "persistent"}
PRIORITIES = {"low", "normal", "high"}


@dataclass(frozen=True)
class CompiledRule:
    graph_id: str
    node_id: str
    rule_index: int
    event: str
    action: str
    target: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompiledReceiver:
    graph_id: str
    node_id: str


@dataclass(frozen=True)
class CompiledReceiverGroup:
    group_id: str
    graph_id: str
    merge_target: CompiledReceiver
    event_profiles: dict[str, str]
    receivers: tuple[CompiledReceiver, ...] = ()


@dataclass(frozen=True)
class RuntimeEventRegistry:
    enabled: bool
    schema_version: int
    rule_index: dict[tuple[str, str, str], tuple[CompiledRule, ...]]
    producer_index: dict[str, dict[str, Any]]
    notice_index: dict[str, dict[str, Any]]
    receiver_group_index: dict[str, CompiledReceiverGroup]
    config: dict[str, Any]
    warnings: tuple[str, ...] = ()


EMPTY_REGISTRY = RuntimeEventRegistry(
    enabled=True,
    schema_version=1,
    rule_index={},
    producer_index={},
    notice_index={},
    receiver_group_index={},
    config={},
)


@dataclass(frozen=True)
class RuntimeEventEnvelope:
    event_id: str
    event: str
    ts: str
    source_graph_id: str
    source_node_id: str
    source_node_type_id: str
    trace_id: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event": self.event,
            "ts": self.ts,
            "source_graph_id": self.source_graph_id,
            "source_node_id": self.source_node_id,
            "source_node_type_id": self.source_node_type_id,
            "trace_id": self.trace_id,
            "payload": dict(self.payload),
        }
