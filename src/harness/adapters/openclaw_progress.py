"""OpenClaw's public plugin event bus -> AgentPark live process events.

The managed plugin frames JSON events on stderr; stdout remains the native
CLI's final JSON result. Ordinary diagnostics remain subprocess diagnostics.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.file_transaction import atomic_write_text
from src.harness.events import HarnessEvents
from .cli_session import string_field, write_json


PREFIX = "AGENTPARK_OPENCLAW_EVENT:"
PLUGIN_ID = "agentpark-progress"
PLUGIN_SOURCE = '''export default {
  id: "agentpark-progress",
  name: "AgentPark progress",
  register(api) {
    const emit = (value) => process.stderr.write("AGENTPARK_OPENCLAW_EVENT:" + JSON.stringify(value) + "\\n");
    api.agent.events.registerAgentEventSubscription({
      id: "progress",
      streams: ["assistant", "thinking", "tool", "lifecycle", "compaction", "approval", "error"],
      handle(event) { emit({ type: "event", event }); }
    });
    emit({ type: "ready", version: 1 });
  }
};
'''


def install_progress_plugin(state_dir: Path) -> dict:
    root = state_dir / PLUGIN_ID
    root.mkdir(exist_ok=True)
    write_json(root / "package.json", {"name": PLUGIN_ID, "version": "1.0.0", "type": "module",
                                      "openclaw": {"extensions": ["./index.js"]}})
    write_json(root / "openclaw.plugin.json", {"id": PLUGIN_ID,
        "configSchema": {"type": "object", "additionalProperties": False, "properties": {}}})
    atomic_write_text(str(root / "index.js"), PLUGIN_SOURCE, encoding="utf-8")
    return {"load": {"paths": [str(root)]},
            "entries": {PLUGIN_ID: {"enabled": True}}}


class OpenClawProgress:
    def __init__(self, events: HarnessEvents):
        self.events = events
        self.ready = False
        self.sequences: dict[str, int] = {}

    def handle_stderr(self, line: str) -> None:
        if not line.startswith(PREFIX):
            return
        envelope = json.loads(line[len(PREFIX):])
        if not isinstance(envelope, dict):
            raise ValueError("OpenClaw progress envelope must be an object.")
        if envelope.get("type") == "ready":
            if envelope.get("version") != 1:
                raise ValueError("Unsupported OpenClaw progress protocol version.")
            self.ready = True
            self.notice("ready", {"message": "OpenClaw progress connected"})
            return
        if envelope.get("type") != "event" or not self.ready:
            raise ValueError("Invalid OpenClaw progress event before bridge readiness.")
        event = envelope.get("event")
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            raise ValueError("OpenClaw event requires an object payload.")
        run_id = string_field(event, "runId")
        sequence = event.get("seq")
        if not run_id or type(sequence) is not int or sequence <= self.sequences.get(run_id, 0):
            raise ValueError("OpenClaw progress events must be ordered per run.")
        self.sequences[run_id] = sequence
        stream, data = string_field(event, "stream"), event["data"]
        if stream == "assistant":
            self.events.text_delta(string_field(data, "delta"))
        elif stream == "thinking":
            self.events.thinking_delta(string_field(data, "delta"))
        elif stream == "tool":
            self.tool(run_id, data)
        elif stream in {"lifecycle", "compaction", "approval", "error"}:
            self.notice(stream, data)
        else:
            raise ValueError(f"Unsupported OpenClaw progress stream: {stream}")

    def tool(self, run_id: str, data: dict) -> None:
        native_id = string_field(data, "toolCallId")
        if not native_id:
            raise ValueError("OpenClaw tool requires a nonempty toolCallId.")
        call_id = run_id + ":" + native_id
        name, phase = string_field(data, "name"), string_field(data, "phase")
        if phase == "input_delta":
            # Native file-edit counters arrive while arguments are generated,
            # before tool execution starts. They do not create a running tool.
            diff = data.get("diff")
            if not isinstance(diff, dict) or any(
                    type(diff.get(key)) is not int or diff[key] < 0 for key in ("added", "removed")):
                raise ValueError("OpenClaw input_delta requires nonnegative integer diff counters.")
            self.notice("tool_input", data, call_id=call_id)
        elif phase == "review":
            review = data.get("review")
            if not isinstance(review, dict) or not string_field(review, "id"):
                raise ValueError("OpenClaw tool review requires a review id.")
            if string_field(review, "status") not in {"in_progress", "approved", "denied", "aborted"}:
                raise ValueError("Unsupported OpenClaw tool review status.")
            self.notice("tool_review", data, call_id=call_id)
        elif phase == "start":
            if call_id in self.events.started:
                raise ValueError("Duplicate OpenClaw tool start.")
            self.events.tool(call_id=call_id, name=name, phase="running", value=data["args"])
        elif phase == "result":
            if type(data.get("isError")) is not bool:
                raise ValueError("OpenClaw tool result requires isError.")
            self.events.tool(call_id=call_id, name=name, phase="completed",
                             value=data.get("result"), error=data["isError"])
        elif phase == "update":
            if call_id not in self.events.started:
                raise ValueError("OpenClaw tool update has no matching start.")
            self.notice("tool_update", data, call_id=call_id)
        else:
            raise ValueError(f"Unsupported OpenClaw tool phase: {phase}")

    def notice(self, stage: str, data: dict, *, call_id: str = "") -> None:
        labels = {"ready": "OpenClaw ready", "lifecycle": "OpenClaw run",
                  "compaction": "Context compaction", "approval": "Approval",
                  "error": "OpenClaw error", "tool_update": "Tool progress",
                  "tool_input": "Preparing tool arguments", "tool_review": "Tool review"}
        name = labels[stage]
        if isinstance(data.get("phase"), str):
            name += ": " + data["phase"]
        if stage == "tool_update":
            name = string_field(data, "name") + ": running"
        elif stage == "tool_input":
            diff = data["diff"]
            name = f"{data['name']}: preparing (+{diff['added']} / -{diff['removed']} lines)"
        elif stage == "tool_review":
            name = f"{data['name']}: review {data['review']['status']}"
        self.events.emit({"type": "runtime_notice", "provider": "openclaw", "source": "openclaw",
                          "name": name, "stage": "openclaw_" + stage,
                          **({"call_id": call_id} if call_id else {}),
                          "message": json.dumps(data, ensure_ascii=False)})

    def finish(self) -> None:
        if not self.ready:
            raise RuntimeError("OpenClaw progress plugin did not load; check the installed OpenClaw plugin API.")
        if self.events.started:
            raise RuntimeError("OpenClaw exited with unfinished tool calls.")
