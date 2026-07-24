from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any


@dataclass(frozen=True)
class ResponsesFunctionCallStreamItem:
    id: str
    call_id: str
    name: str
    arguments: str
    status: str = ""

    def to_response_item(self) -> dict[str, Any]:
        item = {
            "type": "function_call",
            "id": self.id,
            "call_id": self.call_id,
            "name": self.name,
            "arguments": self.arguments,
        }
        if self.status:
            item["status"] = self.status
        return item


@dataclass(frozen=True)
class ResponsesStreamFailure:
    message: str
    code: str
    provider: str = ""
    event_type: str = ""
    status_code: int = 0
    details: dict[str, Any] = field(default_factory=dict)
    event: str = field(default="response_failed", init=False)


@dataclass(frozen=True)
class ResponsesResponseQueued:
    response_id: str
    response: dict[str, Any]
    event: str = field(default="response_queued", init=False)


@dataclass(frozen=True)
class ResponsesResponseCreated:
    response_id: str
    response: dict[str, Any]
    event: str = field(default="response_created", init=False)


@dataclass(frozen=True)
class ResponsesResponseInProgress:
    response_id: str
    response: dict[str, Any]
    event: str = field(default="response_in_progress", init=False)


@dataclass(frozen=True)
class ResponsesOutputItemAdded:
    item_id: str
    output_index: int | None
    item_type: str
    item: dict[str, Any]
    function_call: ResponsesFunctionCallStreamItem | None = None
    event: str = field(default="output_item_added", init=False)


@dataclass(frozen=True)
class ResponsesOutputTextDelta:
    delta: str
    item_id: str = ""
    output_index: int | None = None
    content_index: int | None = None
    event: str = field(default="output_text_delta", init=False)


@dataclass(frozen=True)
class ResponsesRefusalDelta:
    delta: str
    text: str
    item_id: str = ""
    output_index: int | None = None
    content_index: int | None = None
    provider: str = ""
    status: str = "in_progress"
    event: str = field(default="refusal_delta", init=False)


@dataclass(frozen=True)
class ResponsesReasoningDelta:
    delta: str
    item_id: str = ""
    output_index: int | None = None
    content_index: int | None = None
    provider: str = ""
    raw_event_type: str = ""
    event: str = field(default="reasoning_delta", init=False)


@dataclass(frozen=True)
class ResponsesFunctionCallArgumentsDelta:
    item_id: str
    call_id: str
    delta: str
    arguments: str
    event: str = field(default="function_call_arguments_delta", init=False)


@dataclass(frozen=True)
class ResponsesServerToolActivity:
    item_id: str
    output_index: int | None
    item_type: str
    status: str
    item: dict[str, Any]
    event: str = field(default="server_tool_activity", init=False)


@dataclass(frozen=True)
class ResponsesOutputItemDone:
    item_id: str
    output_index: int | None
    item_type: str
    item: dict[str, Any]
    function_call: ResponsesFunctionCallStreamItem | None = None
    event: str = field(default="output_item_done", init=False)


@dataclass(frozen=True)
class ResponsesResponseCompleted:
    response_id: str
    response: dict[str, Any]
    event: str = field(default="response_completed", init=False)


@dataclass(frozen=True)
class ResponsesResponseIncomplete:
    response_id: str
    reason: str
    response: dict[str, Any]
    event: str = field(default="response_incomplete", init=False)


ResponsesStreamEvent = (
    ResponsesStreamFailure
    | ResponsesResponseQueued
    | ResponsesResponseCreated
    | ResponsesResponseInProgress
    | ResponsesOutputItemAdded
    | ResponsesOutputTextDelta
    | ResponsesRefusalDelta
    | ResponsesReasoningDelta
    | ResponsesFunctionCallArgumentsDelta
    | ResponsesServerToolActivity
    | ResponsesOutputItemDone
    | ResponsesResponseCompleted
    | ResponsesResponseIncomplete
)
