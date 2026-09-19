from __future__ import annotations

from typing import Annotated, Literal
from ipaddress import ip_address
import socket
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


DeviceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


def default_device_name() -> str:
    return socket.gethostname()[:100] or "AgentPark"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PeerGrant(Contract):
    peer_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str = Field(min_length=1, max_length=100)
    view: bool = False
    control: bool = False
    collaborate: bool = False
    graph_ids: list[str] = Field(default_factory=list, max_length=100)


class DeviceSetup(Contract):
    enabled: bool = True
    server_ip: str = "203.0.113.10"
    display_name: DeviceName = Field(default_factory=default_device_name)

    @field_validator("server_ip")
    @classmethod
    def validate_ip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return value
        if "%" in value:
            raise ValueError("Scoped IP addresses are not supported.")
        return str(ip_address(value))

    def connection_settings(self) -> "NetworkSettings":
        if self.enabled and not self.server_ip:
            raise ValueError("请填写鉴权服务器 IP。")
        host = f"[{self.server_ip}]" if ":" in self.server_ip else self.server_ip
        return NetworkSettings(enabled=self.enabled, server_ip=self.server_ip,
                               signaling_url=f"wss://{host}/connect" if host else "",
                               stun_urls=[f"stun:{host}:3478"] if host else [],
                               display_name=self.display_name)


class NetworkSettings(Contract):
    """Internal transport configuration; the user-facing contract is DeviceSetup."""
    enabled: bool = True
    server_ip: str = ""
    signaling_url: str = ""
    display_name: DeviceName = Field(default_factory=default_device_name)
    portal_board: bool = True
    stun_urls: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("signaling_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value:
            return value
        url = urlsplit(value)
        local = url.hostname in {"127.0.0.1", "localhost", "::1"}
        if url.scheme != "wss" and not (local and url.scheme == "ws"):
            raise ValueError("Use wss:// for signaling; ws:// is allowed only on loopback.")
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Signaling URL must have a host and no credentials, query or fragment.")
        return value

    @field_validator("stun_urls")
    @classmethod
    def validate_stun(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.startswith("stun:") or len(value) > 255 or any(c.isspace() for c in value):
                raise ValueError("Discovery addresses must use stun:. TURN credentials are issued by the coordinator.")
        return values


class BoardHttpRequest(Contract):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(min_length=1, max_length=4096)
    headers: dict[str, str] = Field(default_factory=dict, max_length=8)
    body: str = Field(default="", max_length=5600000)


class PortalTicket(Contract):
    browser_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    target: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expires_at: int
    signature: str


class PeerCall(Contract):
    operation: Literal["graphs", "nodes", "conversation", "message", "control", "agent_message", "board_http"]
    http: BoardHttpRequest | None = None
    graph_id: str = Field(default="", max_length=150)
    node_id: str = Field(default="", max_length=150)
    text: str = Field(default="", max_length=32000)
    action: Literal["", "stop"] = ""
    message_id: str = Field(default="", max_length=100, pattern=r"^[a-zA-Z0-9_-]*$")
    source_graph_id: str = Field(default="", max_length=150)
    source_node_id: str = Field(default="", max_length=150)


class WireRequest(Contract):
    version: Literal[1] = 1
    kind: Literal["request"] = "request"
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    call: PeerCall


class WireResponse(Contract):
    version: Literal[1] = 1
    kind: Literal["response"] = "response"
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    ok: bool
    result: dict | None = None
    error: str | None = None


class Signal(Contract):
    kind: Literal["connect", "offer", "answer"]
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    target: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_key: str = Field(min_length=40, max_length=60)
    expires_at: int
    sdp: str = Field(default="", max_length=64000)
    signature: str = Field(min_length=80, max_length=100)
