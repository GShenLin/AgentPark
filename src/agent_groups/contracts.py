from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160, pattern=r"^[^/\\\x00-\x1f]+$")]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32000)]
TaskStatus = Literal["todo", "in_progress", "blocked", "done"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class PatchContract(Contract):
    """Omitted patch fields preserve values; only explicitly listed fields clear with null."""
    nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def reject_invalid_null(self):
        for key in self.model_fields_set - self.nullable_fields:
            if getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null; omit it to preserve its value")
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        for name, field in schema.get("properties", {}).items():
            if name in cls.nullable_fields:
                continue
            if "anyOf" in field:
                alternatives = [part for part in field["anyOf"] if part.get("type") != "null"]
                if len(alternatives) == 1:
                    field.pop("anyOf")
                    field.update(alternatives[0])
                else:
                    field["anyOf"] = alternatives
            if field.get("default", ...) is None:
                field.pop("default")
        return schema


class GroupBounds(Contract):
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class GroupMember(Contract):
    node_id: Identifier
    role: str = Field(default="", max_length=2000)


class GroupTask(Contract):
    id: Identifier
    title: Title
    description: str = Field(default="", max_length=32000)
    status: TaskStatus = "todo"
    owner_id: Identifier | None = None
    dependencies: list[Identifier] = Field(default_factory=list)
    evidence: str = Field(default="", max_length=32000)
    revision: int = Field(default=1, ge=1)
    created_at: str
    updated_at: str


class AgentGroup(Contract):
    id: Identifier
    name: Title
    objective: str = Field(default="", max_length=32000)
    bounds: GroupBounds
    members: list[GroupMember] = Field(default_factory=list)
    tasks: list[GroupTask] = Field(default_factory=list)
    revision: int = Field(default=1, ge=1)
    dissolved: bool = False
    private: bool = False
    created_at: str
    updated_at: str


class CreateGroup(Contract):
    name: Title
    members: list[GroupMember] = Field(min_length=1)
    bounds: GroupBounds
    objective: str = Field(default="", max_length=32000)

    @model_validator(mode="after")
    def unique_members(self):
        ids = [member.node_id for member in self.members]
        if len(ids) != len(set(ids)):
            raise ValueError("group members must be unique")
        return self


class CreateTask(Contract):
    title: Title
    description: str = Field(default="", max_length=32000)
    owner_id: Identifier | None = None
    dependencies: list[Identifier] = Field(default_factory=list)


class UpdateTask(PatchContract):
    nullable_fields = frozenset({"owner_id"})
    expected_revision: int = Field(ge=1)
    title: Title | None = None
    description: str | None = Field(default=None, max_length=32000)
    status: TaskStatus | None = None
    owner_id: Identifier | None = None
    dependencies: list[Identifier] | None = None
    evidence: str | None = Field(default=None, max_length=32000)

class MessageAttachment(Contract):
    uri: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8192)]
    name: str = Field(default="", max_length=1024)
    kind: Literal["image", "video", "audio", "doc", "file", "url"]
    mime: str = Field(default="", max_length=255)
    source: str = Field(default="", max_length=160)


class MessageContent(Contract):
    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32000)] = ""
    attachments: list[MessageAttachment] = Field(default_factory=list, max_length=100)
    request_id: Identifier

    @model_validator(mode="after")
    def require_content(self):
        if not self.text and not self.attachments:
            raise ValueError("a message requires text or attachments")
        return self


class PublishMessage(MessageContent):
    recipient_id: Identifier | None = None
    intent: Literal["action", "update"] = "action"
    broadcast_reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_routing(self):
        if self.intent == "update" and (self.recipient_id is not None or self.broadcast_reason):
            raise ValueError("shared updates have no recipient or broadcast reason")
        if self.recipient_id is not None and self.broadcast_reason:
            raise ValueError("direct messages have no broadcast reason")
        return self


class DirectMessage(MessageContent):
    recipient_id: Identifier


class BroadcastMessage(MessageContent):
    broadcast_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class UpdateGroup(PatchContract):
    expected_revision: int = Field(ge=1)
    name: Title | None = None
    objective: str | None = Field(default=None, max_length=32000)
    bounds: GroupBounds | None = None

class MoveMember(Contract):
    target_group_id: Identifier | None
    expected_source: Identifier | None
    role: str = Field(default="", max_length=2000)


class UpdateMemberRole(Contract):
    expected_role: str = Field(max_length=2000)
    role: str = Field(max_length=2000)


class UpdatePlan(Contract):
    expected_name: Title
    expected_objective: str = Field(max_length=32000)
    name: Title
    objective: str = Field(max_length=32000)


class GroupError(ValueError):
    """A rejected command, never an implicit state reset."""


class GroupNotFound(GroupError):
    pass


class GroupConflict(GroupError):
    pass


class GroupPermissionError(GroupError):
    pass
