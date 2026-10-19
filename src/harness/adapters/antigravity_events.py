"""Validate native stream-json frames and project step lifecycles into the node."""
from __future__ import annotations

import json
from collections.abc import Callable

from src.harness.events import HarnessEvents
from .cli_session import string_field


class AntigravityEvents:
    def __init__(self, events: HarnessEvents, *, model: str, conversation: str,
                 on_init: Callable[[str], None]):
        self.events = events
        self.model = model
        self.conversation = conversation
        self.on_init = on_init
        self.initialized = False
        self.result: dict | None = None
        self.completed_tools: set[str] = set()
        self.diagnostics: list[str] = []

    def diagnostic(self, line: str) -> None:
        self.diagnostics.append(line.rstrip())
        self.diagnostics = self.diagnostics[-20:]

    def handle(self, line: str) -> None:
        frame = json.loads(line)
        if not isinstance(frame, dict) or self.result is not None:
            raise ValueError("Invalid Antigravity stream frame or frame after result.")
        event = frame.get("event")
        if event == "init":
            if self.initialized:
                raise ValueError("Duplicate Antigravity init.")
            conversation = string_field(frame, "conversation_id")
            if self.conversation and conversation != self.conversation:
                raise ValueError("Antigravity resumed a different conversation.")
            init = frame.get("init")
            if not isinstance(init, dict) or init.get("model") != self.model:
                raise ValueError("Antigravity selected a different model than requested.")
            self.conversation, self.initialized = conversation, True
            self.on_init(conversation)
        elif event == "step_update":
            step = frame.get("step_update")
            self._check_conversation(step)
            self._step(step)
        elif event == "result":
            result = frame.get("result")
            # Startup/authentication failures can produce an error before init.
            if not isinstance(result, dict):
                raise ValueError("Invalid Antigravity result.")
            if result.get("status") != "SUCCESS":
                raise RuntimeError(f"Antigravity {result.get('status')}: {result.get('error') or result.get('response') or 'No successful result.'}")
            self._check_conversation(result)
            if not isinstance(result.get("response"), str):
                raise ValueError("Antigravity result response must be a string.")
            denied = result.get("denied_actions", [])
            if not isinstance(denied, list):
                raise ValueError("Invalid Antigravity denied_actions.")
            self.result = result
        else:
            raise ValueError(f"Unsupported Antigravity stream event: {event!r}")

    def _check_conversation(self, data: object) -> None:
        if not self.initialized or not isinstance(data, dict) or data.get("conversation_id") != self.conversation:
            raise ValueError("Antigravity event has no matching initialized conversation.")

    def _step(self, step: dict) -> None:
        index, state, kind = step.get("step_index"), step.get("state"), step.get("step_type")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("Invalid Antigravity step_index.")
        if state not in {"ACTIVE", "DONE", "ERROR"}:
            raise ValueError(f"Unsupported Antigravity step state: {state!r}")
        if kind == "agent_response":
            if "text_delta" in step:
                delta = step["text_delta"]
                if not isinstance(delta, str):
                    raise ValueError("Antigravity text_delta must be a string.")
                if delta:
                    self.events.text_delta(delta)
        elif kind == "tool":
            call_id = f"{self.conversation}:{index}"
            name = string_field(step, "tool_name")
            info = step.get("tool_info")
            if not isinstance(info, dict) or info.get("name") != name:
                raise ValueError("Invalid Antigravity tool_info.")
            if "parameters" in info and not isinstance(info["parameters"], dict):
                raise ValueError("Antigravity tool parameters must be an object.")
            if call_id in self.completed_tools:
                raise ValueError("Antigravity updated an already completed tool.")
            if call_id not in self.events.started:
                self.events.tool(call_id=call_id, name=name, phase="running", value=info.get("parameters", {}))
            if state in {"DONE", "ERROR"}:
                self.events.tool(call_id=call_id, name=name, phase="done", value=info, error=state == "ERROR")
                self.completed_tools.add(call_id)
        elif kind not in {"user_input", "system_message", "checkpoint"}:
            raise ValueError(f"Unsupported Antigravity step_type: {kind!r}")

    def abort(self, error: Exception) -> None:
        for call_id in list(self.events.started):
            self.events.tool(call_id=call_id, name=self.events.tools[call_id]["name"],
                             phase="done", value=str(error), error=True)

    def finish(self):
        if self.result is None:
            raise RuntimeError("Antigravity ended without a successful result. " + "\n".join(self.diagnostics))
        if self.result.get("denied_actions"):
            raise RuntimeError("Antigravity permission required; headless mode cannot prompt. "
                               + json.dumps(self.result["denied_actions"], ensure_ascii=False)
                               + "\n" + "\n".join(self.diagnostics))
        if self.events.started:
            raise RuntimeError("Antigravity ended with unfinished tool steps.")
        if not self.result["response"].strip() and any(tool["status"] == "failed" for tool in self.events.tools.values()):
            raise RuntimeError("Antigravity produced no response after a tool failure; see the failed tool details.")
        return self.events.done(self.result["response"])
