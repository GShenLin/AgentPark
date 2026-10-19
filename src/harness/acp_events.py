"""Strict ACP text and partial tool lifecycle projection shared by native clients."""
from __future__ import annotations

from src.harness.contracts import HarnessResult
from src.harness.events import HarnessEvents
from .adapters.cli_session import string_field


class AcpEvents:
    CONTROL_UPDATES = {"available_commands_update", "config_option_update", "current_mode_update",
                       "session_info_update", "usage_update", "plan"}

    def __init__(self, events: HarnessEvents):
        self.events = events
        self.session_id = ""
        self.pending: list[dict] = []
        self.tools: dict[str, dict] = {}

    def bind(self, session_id: str) -> None:
        if not session_id:
            raise ValueError("ACP returned an empty session id.")
        self.session_id = session_id
        for params in self.pending:
            self.handle(params)
        self.pending.clear()

    def handle(self, params: dict) -> None:
        if not self.session_id:
            if len(self.pending) >= 100:
                raise ValueError("Too many ACP updates before session creation.")
            self.pending.append(params)
            return
        if params.get("sessionId") != self.session_id:
            raise ValueError("ACP ACP update belongs to a different session.")
        update = params.get("update")
        if not isinstance(update, dict):
            raise ValueError("ACP ACP update must be an object.")
        kind = string_field(update, "sessionUpdate")
        if kind in {"agent_message_chunk", "agent_thought_chunk"}:
            content = update.get("content")
            if not isinstance(content, dict) or content.get("type") != "text":
                raise ValueError("ACP currently supports text response blocks only.")
            emit = self.events.text_delta if kind == "agent_message_chunk" else self.events.thinking_delta
            emit(string_field(content, "text"))
        elif kind in {"tool_call", "tool_call_update"}:
            self._tool(update, initial=kind == "tool_call")
        elif kind not in self.CONTROL_UPDATES:
            raise ValueError(f"Unsupported ACP ACP update: {kind}")

    def _tool(self, update: dict, *, initial: bool) -> None:
        call_id = string_field(update, "toolCallId")
        if not call_id:
            raise ValueError("ACP tool requires a nonempty id.")
        if initial:
            if call_id in self.tools:
                raise ValueError("Duplicate ACP tool call.")
            title = string_field(update, "title")
            name = string_field(update, "name") if "name" in update else title
            self.tools[call_id] = {"name": name}
            self.events.tool(call_id=call_id, name=name, phase="running", value=update.get("rawInput"))
        elif call_id not in self.tools or call_id not in self.events.started:
            raise ValueError("ACP tool update has no active call.")
        tool = self.tools[call_id]
        tool.update(update)
        if "rawInput" in update:
            self.events.tools[call_id]["arguments"] = update["rawInput"]
        status = tool.get("status")
        if status not in {None, "pending", "in_progress", "completed", "failed"}:
            raise ValueError(f"Unsupported ACP tool status: {status}")
        if status in {"completed", "failed"}:
            output = tool["rawOutput"] if "rawOutput" in tool else tool.get("content", [])
            if "rawOutput" in tool and tool.get("content"):
                output = {"output": tool["rawOutput"], "content": tool["content"]}
            self.events.tool(call_id=call_id, name=tool["name"], phase="completed", value=output,
                             error=status == "failed")

    def finish(self, result: dict) -> HarnessResult:
        if result.get("stopReason") != "end_turn":
            raise RuntimeError(f"ACP turn ended: {result.get('stopReason')}")
        if self.events.started:
            raise ValueError("ACP returned with unfinished tool calls.")
        if not self.events.text:
            raise RuntimeError("ACP ended without assistant text.")
        return self.events.done(self.events.text)
