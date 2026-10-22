"""Opt-in real CLI integration against a local model stub; no external model calls."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.harness.contracts import HarnessContext
from src.harness.process_manager import HarnessProcesses
from src.harness.install_manager import command_argv


@pytest.fixture
def cli_workspace(harness_id, tmp_path):
    if harness_id == "minimax_code":
        # The published Windows SQLite backup does not support paths over MAX_PATH.
        original_cwd = Path.cwd()
        with TemporaryDirectory(prefix="ap-mc-") as directory:
            try:
                yield Path(directory)
            finally:
                os.chdir(original_cwd)
    else:
        yield tmp_path


@pytest.mark.parametrize("explicit_workspace", [False, True])
@pytest.mark.parametrize("harness_id,env_key", [
    ("pi", "AGENTPARK_TEST_PI_ENTRY"),
    ("deepseek_harness", "AGENTPARK_TEST_DSH_ENTRY"),
    ("openclaw", "AGENTPARK_TEST_OPENCLAW_ENTRY"),
    ("hermes_agent", "AGENTPARK_TEST_HERMES_PYTHON"),
    ("minimax_code", "AGENTPARK_TEST_MCODE_ENTRY"),
    ("opencode", "AGENTPARK_TEST_OPENCODE_ENTRY"),
    ("antigravity", "AGENTPARK_TEST_AGY_ENTRY"),
])
def test_real_cli_routes_selected_model_and_resumes(harness_id, env_key, explicit_workspace, cli_workspace, monkeypatch):
    tmp_path = cli_workspace
    entry = os.environ.get(env_key)
    if not entry:
        pytest.skip(f"Set {env_key} to the installed CLI JS entry point.")
    timings = []
    turn_start = 0.0
    first_request = None
    first_delta = None
    received = []
    authorizations = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            nonlocal first_request
            if first_request is None:
                first_request = time.perf_counter() - turn_start
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(payload)
            authorizations.append(self.headers.get("Authorization"))
            chunks = [
                {"id": "chat-test", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "HARNESS_OK"}, "finish_reason": None}]},
                {"id": "chat-test", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}},
            ]
            body = ("".join("data: " + json.dumps(item) + "\n\n" for item in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {"id": "p", "type": "openai", "model": "first", "models": ["first", "second"],
              "supportmode": ["chat"], "apiKey": "stub-secret", "authMode": "api_key",
              "baseUrl": f"http://127.0.0.1:{server.server_port}/v1"}
    monkeypatch.setattr("src.config_loader.ConfigLoader.get_provider_config",
                        lambda self, key: {**config, "id": key, "apiKey": "stub-secret-" + key})
    installed_command = command_argv(harness_id)
    assert Path(installed_command[-1]).resolve() == Path(entry).resolve()
    module = "openclaw" if harness_id == "openclaw" else "resident"
    monkeypatch.setattr(f"src.harness.adapters.{module}.command_argv", lambda key: installed_command)
    host = tmp_path / "host"
    host.mkdir()
    (host / "AGENTS.md").write_text("HOST_INSTRUCTIONS_MUST_NOT_LEAK", encoding="utf-8")
    skill = host / ".agents" / "skills" / "host-only"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: host-only\ndescription: HOST_SKILL_MUST_NOT_LEAK\n---\nHost-only instructions.\n",
        encoding="utf-8")
    monkeypatch.chdir(host)
    node = tmp_path / "node"
    node.mkdir()
    work = tmp_path / "explicit-workspace"
    work.mkdir()
    context = HarnessContext(str(node / "config.json"), str(node),
                             {"provider_id": "p", "model": "second",
                              "working_path": str(work) if explicit_workspace else "", "timeout_seconds": 90})
    try:
        for index, (provider_id, model) in enumerate([
                ("p", "second"), ("p", "first"), ("other", "first"), ("p", "second")]):
            context.values.update(provider_id=provider_id, model=model)
            first_request = first_delta = None
            turn_start = time.perf_counter()
            def on_event(event):
                nonlocal first_delta
                if first_delta is None and event.get("type") in {"node_message_delta", "node_thinking_delta"}:
                    first_delta = time.perf_counter() - turn_start
            context.values["stream_callback"] = on_event
            question = f"Turn marker CONTINUITY_{index}. Say HARNESS_OK. Do not use tools."
            assert HarnessProcesses.instance().execute(harness_id, context, question).text.strip() == "HARNESS_OK"
            timings.append({"turn": index, "first_request_seconds": first_request,
                            "first_output_seconds": first_delta, "total_seconds": time.perf_counter() - turn_start})
        report = os.environ.get("AGENTPARK_TEST_TIMING_REPORT")
        if report:
            with open(report, "a", encoding="utf-8") as stream:
                stream.write(json.dumps({"harness": harness_id, "explicit_workspace": explicit_workspace, "timings": timings}) + "\n")
        if harness_id in {"antigravity", "opencode"}:
            # Native auxiliary title generation also uses the selected gateway.
            main = [(item, auth) for item, auth in zip(received, authorizations) if not any("title generator" in str(m.get("content", "")).lower() or "conversation title" in str(m.get("content", "")).lower() for m in item["messages"] if m["role"] == "system")]
            assert main and all(auth.startswith("Bearer stub-secret-") for auth in authorizations)
            received[:], authorizations[:] = map(list, zip(*main))
        assert len(received) == 4
        assert [item["model"] for item in received] == ["second", "first", "first", "second"]
        assert authorizations == ["Bearer stub-secret-p", "Bearer stub-secret-p",
                                  "Bearer stub-secret-other", "Bearer stub-secret-p"]
        for index, item in enumerate(received):
            history = json.dumps(item["messages"])
            for previous in range(index + 1):
                assert f"CONTINUITY_{previous}" in history
            if index:
                assert any(message["role"] == "assistant" and "HARNESS_OK" in json.dumps(message)
                           for message in item["messages"])
        wire = json.dumps(received)
        assert "HOST_INSTRUCTIONS_MUST_NOT_LEAK" not in wire
        assert "HOST_SKILL_MUST_NOT_LEAK" not in wire
        assert "host-only" not in wire
        assert not (host / "SOUL.md").exists()
        for path in (node / ".harness").rglob("*"):
            if path.is_file() and path.suffix in {".json", ".yaml"}:
                assert "stub-secret" not in path.read_text(encoding="utf-8")
    finally:
        HarnessProcesses.instance().stop(node)
        if harness_id == "openclaw":
            from src.harness.openclaw_session import OpenClawSessions
            OpenClawSessions.instance().close_under(node)
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
