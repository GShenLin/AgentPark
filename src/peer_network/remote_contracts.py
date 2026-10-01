"""Remote execution contracts shared by discovery and authenticated peer RPC."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RemoteDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    worker_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    host_kind: str = Field(min_length=1, max_length=50)
    workspace_path: str = Field(min_length=1, max_length=4096)
    capabilities: list[str] = Field(max_length=100)
    online: bool


class RemoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    action: Literal["execute", "cancel"]
    # Routed IDs contain "peer:" + 64-hex host + ":" + a 128-character worker ID.
    worker_id: str = Field(min_length=1, max_length=198)
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    tool_name: str = Field(default="", max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)
    working_path: str = Field(default="", max_length=4096)
    timeout_seconds: float = Field(default=3600.0, gt=0, le=86400)

    def task_payload(self) -> dict:
        if self.action != "execute" or not self.tool_name or not self.working_path:
            raise ValueError("Remote execution requires a tool and an absolute WorkingPath.")
        return self.model_dump(exclude={"action"})


class RemoteHost(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    peer_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    remote_workers: list[RemoteDescriptor] = Field(max_length=100)


def validate_descriptors(payload: object) -> list[dict]:
    if not isinstance(payload, list) or len(payload) > 100:
        raise ValueError("remote_workers must be an array of at most 100 workers.")
    workers = [RemoteDescriptor.model_validate(item).model_dump() for item in payload]
    if len({item["worker_id"] for item in workers}) != len(workers):
        raise ValueError("Duplicate remote worker identity.")
    return workers
