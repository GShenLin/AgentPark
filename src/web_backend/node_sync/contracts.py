from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[\w.-]+$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Selection(Contract):
    graph_id: Identifier
    node_id: Identifier | None = None


class Endpoint(Selection):
    remote_id: str = Field(min_length=1, max_length=200)


class SyncRequest(Contract):
    source: Endpoint
    target: Endpoint

    @model_validator(mode="after")
    def matching_scope(self):
        if bool(self.source.node_id) != bool(self.target.node_id):
            raise ValueError("两边都选节点，或两边都不选节点（同步整个 Graph）。")
        if self.source == self.target:
            raise ValueError("来源与目标不能相同。")
        return self


class Record(Contract):
    id: str = Field(min_length=1, max_length=300)
    role: Literal["user", "human", "assistant", "agent"]
    parts: list[dict]
    created_at: str = Field(min_length=10, max_length=100)
    trace_id: str | None = None


class Entry(Contract):
    origin: str = Field(min_length=1, max_length=600)
    turn: str = Field(min_length=1, max_length=600)
    record: Record
    digest: Digest
    archive: bool


class Node(Contract):
    id: Identifier
    config: dict | None = None
    entries: list[Entry]


class Bundle(Contract):
    version: Literal[1] = 1
    instance: str
    selection: Selection
    graph: dict | None = None
    groups: list[dict] = Field(default_factory=list)
    nodes: list[Node]
    blobs: dict[Digest, int]
    warnings: list[str] = Field(default_factory=list)


class Chunk(Contract):
    offset: int = Field(ge=0)
    data: str = Field(max_length=360000)
    total: int = Field(ge=0)


class Prepare(Contract):
    manifest: Digest
    target: Selection


class CreateGraph(Contract):
    id: Identifier
    name: str = Field(min_length=1, max_length=200)


class BlobKey(Contract):
    sha: Digest


class BlobRead(BlobKey):
    offset: int = Field(ge=0)


class BlobWrite(BlobKey):
    chunk: Chunk


class ApplyStep(Contract):
    ticket: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]
    index: int = Field(ge=-1)


class SyncConflict(ValueError):
    pass
