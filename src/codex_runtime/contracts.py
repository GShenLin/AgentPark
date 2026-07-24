from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Literal


ToolKind = Literal["function", "custom", "tool_search"]


class CodexProtocolError(ValueError):
    """Raised when a provider cannot preserve a Codex Responses contract."""


@dataclass(frozen=True)
class CanonicalTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    kind: ToolKind = "function"
    namespace: str = ""

    @property
    def wire_name(self) -> str:
        return _wire_tool_name(self.namespace, self.name)


@dataclass(frozen=True)
class CanonicalToolCall:
    call_id: str
    name: str
    arguments: str
    kind: ToolKind = "function"
    namespace: str = ""

    @property
    def wire_name(self) -> str:
        return _wire_tool_name(self.namespace, self.name)


@dataclass(frozen=True)
class CanonicalMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]]
    tool_calls: tuple[CanonicalToolCall, ...] = ()
    tool_call_id: str = ""
    tool_name: str = ""


@dataclass(frozen=True)
class CanonicalRequest:
    model: str
    messages: tuple[CanonicalMessage, ...]
    tools: tuple[CanonicalTool, ...]
    stream: bool
    tool_choice: object = "auto"
    parallel_tool_calls: bool = True
    reasoning_effort: str = ""
    max_output_tokens: int | None = None


@dataclass
class CanonicalResult:
    response_id: str
    text: str = ""
    tool_calls: list[CanonicalToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _wire_tool_name(namespace: str, name: str) -> str:
    raw = f"{namespace}__{name}" if namespace else name
    normalized = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)
    if normalized == raw and len(normalized) <= 64:
        return normalized
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{normalized[:49]}__{digest}"
