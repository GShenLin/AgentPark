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
    event: str = field(default="response_failed", init=False)


@dataclass(frozen=True)
class ResponsesResponseCreated:
    response_id: str
    response: dict[str, Any]
    event: str = field(default="response_created", init=False)


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
class ResponsesFunctionCallArgumentsDelta:
    item_id: str
    call_id: str
    delta: str
    arguments: str
    event: str = field(default="function_call_arguments_delta", init=False)


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


ResponsesStreamEvent = (
    ResponsesStreamFailure
    | ResponsesResponseCreated
    | ResponsesOutputItemAdded
    | ResponsesOutputTextDelta
    | ResponsesFunctionCallArgumentsDelta
    | ResponsesOutputItemDone
    | ResponsesResponseCompleted
)
