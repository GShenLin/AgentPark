"""One bounded native process per turn, resuming only the node's exact conversation."""
from __future__ import annotations

import json

from src.harness.contracts import HarnessContext, HarnessResult
from src.harness.execution import execution_session
from src.harness.install_manager import command_argv
from src.harness.process import run_process
from .antigravity_config import load_request
from .antigravity_events import AntigravityEvents
from .cli_session import string_field, write_json


class Adapter:
    def run(self, text: str, context: HarnessContext) -> HarnessResult:
        request = load_request(context)
        with execution_session("antigravity", "antigravity", request, context) as events:
            path = request.state_dir / "session.json"
            conversation = ""
            if path.exists():
                state = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(state, dict) or state.get("cwd") != request.cwd:
                    raise ValueError("Antigravity working directory changed. Restore it or clear this node's memory first.")
                conversation = string_field(state, "conversation_id")
            parser = AntigravityEvents(events, model=request.model, conversation=conversation,
                on_init=lambda value: write_json(path, {"conversation_id": value, "cwd": request.cwd}))
            argv = [*command_argv("antigravity"), "--input-format", "stream-json", "--output-format", "stream-json",
                    "--model", request.model, "--disable-slash-commands"]
            if conversation:
                argv += ["--conversation", conversation]
            if request.mode:
                argv += ["--mode", request.mode]
            if request.effort:
                argv += ["--effort", request.effort]
            prompt = f"{request.instruction}\n\n{text}" if request.instruction else text
            # A JSON stdin frame avoids Windows command-line size limits and shell quoting.
            # EOF closes input; the native CLI completes this turn before exiting.
            stdin = json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False) + "\n"
            try:
                run_process(argv, cwd=request.cwd, stdin=stdin, timeout=request.timeout,
                            cancel_source=request.cancel_source, on_line=parser.handle, on_stderr_line=parser.diagnostic)
                return parser.finish()
            except Exception as exc:
                parser.abort(exc)
                raise
