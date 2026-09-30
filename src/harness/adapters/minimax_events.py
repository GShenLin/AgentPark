"""Strict ACP projection for MiniMax Code text and partial tool lifecycle updates."""
from __future__ import annotations

from src.harness.contracts import HarnessResult
from src.harness.events import HarnessEvents
from .cli_session import string_field


class MiniMaxEvents:
    CONTROL_UPDATES = {"available_commands_update", "config_option_update", "current_mode_update",
                       "session_info_update", "usage_update", "plan"}

    def __init__(self, events: HarnessEvents):
        self.events = events
        self.session_id = ""
        self.pending: list[dict] = []
        self.tools: dict[str, dict] = {}

    def bind(self, session_id: str) -> None:
        if not session_id:
            raise ValueError("MiniMax Code returned an empty session id.")
        self.session_id = session_id
        for params in self.pending:
            self.handle(params)
        self.pending.clear()

    def handle(self, params: dict) -> None:
        if not self.session_id:
            if len(self.pending) >= 100:
                raise ValueError("Too many MiniMax Code updates before session creation.")
            self.pending.append(params)
            return
        if params.get("sessionId") != self.session_id:
            raise ValueError("MiniMax Code ACP update belongs to a different session.")
        update = params.get("update")
        if not isinstance(update, dict):
            raise ValueError("MiniMax Code ACP update must be an object.")
        kind = string_field(update, "sessionUpdate")
        if kind in {"agent_message_chunk", "agent_thought_chunk"}:
            content = update.get("content")
            if not isinstance(content, dict) or content.get("type") != "text":
                raise ValueError("MiniMax Code currently supports text response blocks only.")
            emit = self.events.text_delta if kind == "agent_message_chunk" else self.events.thinking_delta
            emit(string_field(content, "text"))
        elif kind in {"tool_call", "tool_call_update"}:
            self._tool(update, initial=kind == "tool_call")
        elif kind not in self.CONTROL_UPDATES:
            raise ValueError(f"Unsupported MiniMax Code ACP update: {kind}")

    def _tool(self, update: dict, *, initial: bool) -> None:
        call_id = string_field(update, "toolCallId")
        if not call_id:
            raise ValueError("MiniMax Code tool requires a nonempty id.")
        if initial:
            if call_id in self.tools:
                raise ValueError("Duplicate MiniMax Code tool call.")
            title = string_field(update, "title")
            name = string_field(update, "name") if "name" in update else title
            self.tools[call_id] = {"name": name}
            self.events.tool(call_id=call_id, name=name, phase="running", value=update.get("rawInput"))
        elif call_id not in self.tools or call_id not in self.events.started:
            raise ValueError("MiniMax Code tool update has no active call.")
        tool = self.tools[call_id]
        tool.update(update)
        if "rawInput" in update:
            self.events.tools[call_id]["arguments"] = update["rawInput"]
        status = tool.get("status")
        if status not in {None, "pending", "in_progress", "completed", "failed"}:
            raise ValueError(f"Unsupported MiniMax Code tool status: {status}")
        if status in {"completed", "failed"}:
            output = tool["rawOutput"] if "rawOutput" in tool else tool.get("content", [])
            self.events.tool(call_id=call_id, name=tool["name"], phase="completed", value=output,
                             error=status == "failed")

    def finish(self, result: dict) -> HarnessResult:
        if result.get("stopReason") != "end_turn":
            raise RuntimeError(f"MiniMax Code turn ended: {result.get('stopReason')}")
        if self.events.started:
            raise ValueError("MiniMax Code returned with unfinished tool calls.")
        if not self.events.text:
            raise RuntimeError("MiniMax Code ended without assistant text.")
        return self.events.done(self.events.text)
