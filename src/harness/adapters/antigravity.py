"""Resident native stream-json process with an independently persisted conversation."""
from __future__ import annotations

import json

from src.harness.jsonl_process import JsonlProcess
from .resident import ResidentCliAdapter
from .antigravity_config import execution_options, RUNTIME_MODEL
from .antigravity_events import AntigravityEvents
from .cli_session import string_field, write_json



class Adapter(ResidentCliAdapter):
    harness_id = "antigravity"

    def options(self, context):
        return execution_options(context)

    def open(self, request, argv, env, options, events):
        env.update(AGY_LLM_GATEWAY_URL=self.lease.base_url,
                   AGY_LLM_GATEWAY_API_KEY=self.lease.token,
                   AGY_LLM_GATEWAY_WIRE_PROTOCOL="openai",
                   AGY_LLM_GATEWAY_MODELS=RUNTIME_MODEL,
                   AGY_CLI_DISABLE_AUTO_UPDATE="1")
        path = request.state_dir / "session.json"
        conversation = ""
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("cwd") != request.cwd:
                raise ValueError("Antigravity working directory changed. Restore it or clear this node's memory first.")
            conversation = string_field(state, "conversation_id")
        self.parser = AntigravityEvents(events, model=RUNTIME_MODEL, conversation=conversation,
            on_init=lambda value: write_json(path, {"conversation_id": value, "cwd": request.cwd}))
        argv = [*argv, "--input-format", "stream-json", "--output-format", "stream-json",
                "--model", RUNTIME_MODEL, "--disable-slash-commands"]
        if conversation:
            argv += ["--conversation", conversation]
        if options.mode:
            argv += ["--mode", options.mode]
        if options.auto_approve:
            argv.append("--dangerously-skip-permissions")
        self.client = JsonlProcess(argv, cwd=request.cwd, env=env,
            timeout=request.timeout, cancel_source=request.cancel_source)
        self.parser.handle(json.dumps(self.client.receive(), ensure_ascii=False))
        if not self.parser.initialized:
            raise RuntimeError("Antigravity did not initialize its conversation.")

    def turn(self, text, request, events):
        parser = AntigravityEvents(events, model=RUNTIME_MODEL,
            conversation=self.parser.conversation, on_init=self.parser.on_init)
        parser.initialized = True
        prompt = f"{request.instruction}\n\n{text}" if request.instruction else text
        self.client.send({"event": "user", "message": {"content": prompt}})
        try:
            while parser.result is None:
                parser.handle(json.dumps(self.client.receive(), ensure_ascii=False))
            return parser.finish()
        except Exception as exc:
            parser.abort(exc)
            raise
