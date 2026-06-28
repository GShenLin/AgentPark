from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReceiverKey:
    graph_id: str
    node_id: str

    def text(self) -> str:
        return f"{self.graph_id}:{self.node_id}"


@dataclass(frozen=True)
class ReceiverRuntimeConfig:
    account_id: str
    receiver_name: str
    active: bool
    poll_timeout_seconds: int


@dataclass(frozen=True)
class ReceiverConfigRef:
    graph_id: str
    node_id: str
    cfg: dict


@dataclass(frozen=True)
class RoutedEnvelope:
    envelope: dict | None
    graph_id: str
    node_id: str
    command_matched: bool = False
