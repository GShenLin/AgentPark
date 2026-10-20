from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nodes.antigravity_node import Node
from src.harness.adapters.antigravity import Adapter
from src.harness.adapters.antigravity_config import DEFAULT_MODEL, load_request
from src.harness.adapters.antigravity_events import AntigravityEvents
from src.harness.contracts import HarnessContext
from src.harness.events import HarnessEvents
from src.harness.memory_reset import clear_harness_memory


def context(tmp_path, **values):
    return HarnessContext(str(tmp_path / "config.json"), str(tmp_path), values)


def test_native_schema_and_reset_preserve_workspace(tmp_path):
    schema = Node().get_config_schema({"provider_id": "unrelated"})
    assert "provider_id" not in schema and "model" not in schema
    request = load_request(context(tmp_path))
    assert request.model == DEFAULT_MODEL and request.mode == "" and request.auto_approve is False
    assert load_request(context(tmp_path, native_model="gemini-4-argon-high")).state_dir == request.state_dir
    work = Path(request.cwd) / "keep.txt"
    work.write_text("user work", encoding="utf-8")
    clear_harness_memory(str(tmp_path), {"type_id": "antigravity_node"})
    assert not request.state_dir.exists() and work.read_text() == "user work"


@pytest.mark.parametrize("values", [
    {"access_role": "nondeveloper"}, {"native_model": ""}, {"native_model": "a b"},
    {"native_mode": "bypassPermissions"}, {"native_effort": "unknown"}, {"native_effort": []},
    {"timeout_seconds": False}, {"timeout_seconds": float("nan")}, {"working_path": "Z:/missing-agy-workspace"},
    {"native_auto_approve": "true"}, {"native_auto_approve": 1}, {"native_auto_approve": None},
    {"native_auto_approve": True, "access_role": "nondeveloper"},
])
def test_invalid_request_never_launches(tmp_path, values):
    with pytest.raises(ValueError):
        load_request(context(tmp_path, **values))


def init_frame(model=DEFAULT_MODEL, conversation="session-one"):
    return {"event": "init", "conversation_id": conversation, "init": {"model": model}}


def step_frame(kind="agent_response", state="DONE", **fields):
    return {"event": "step_update", "step_update": {"conversation_id": "session-one",
        "step_index": 1, "step_type": kind, "state": state, **fields}}


def result_frame(**fields):
    return {"event": "result", "result": {"conversation_id": "session-one", "status": "SUCCESS",
            "response": "hello", **fields}}


def parser():
    output, saved = [], []
    value = AntigravityEvents(HarnessEvents("antigravity", "antigravity", output.append),
                             model=DEFAULT_MODEL, conversation="", on_init=saved.append)
    return value, output, saved


def feed(value, *frames):
    for frame in frames:
        value.handle(json.dumps(frame))


def test_stream_deltas_tool_error_and_headless_denial_are_not_success():
    value, output, saved = parser()
    tool = {"name": "write_to_file", "parameters": {"TargetFile": "proof.txt"}}
    feed(value, init_frame(), step_frame(text_delta="hello"),
         step_frame("tool", "ACTIVE", tool_name="write_to_file", tool_info=tool),
         step_frame("tool", "ERROR", tool_name="write_to_file", tool_info={**tool, "error": {"message": "denied"}}),
         result_frame(response="", denied_actions=[{"action": "write_file"}]))
    value.diagnostic("permission required")
    with pytest.raises(RuntimeError, match="permission required"):
        value.finish()
    assert saved == ["session-one"]
    assert [e["type"] for e in output] == ["node_message_delta", "tool_call_start", "tool_call_end"]
    assert output[-1]["status"] == "failed"


@pytest.mark.parametrize("frames,match", [
    ([init_frame("wrong-model")], "different model"),
    ([init_frame(), init_frame()], "Duplicate"),
    ([step_frame(text_delta="hello")], "matching initialized"),
    ([init_frame(), result_frame(conversation_id="another")], "matching initialized"),
    ([result_frame(status="ERROR", error="login required")], "login required"),
    ([init_frame(), step_frame(step_index=True)], "step_index"),
    ([init_frame(), step_frame(text_delta={})], "text_delta"),
    ([init_frame(), result_frame(), step_frame()], "frame after result"),
])
def test_protocol_drift_fails_explicitly(frames, match):
    value, _, _ = parser()
    with pytest.raises((ValueError, RuntimeError), match=match):
        feed(value, *frames)


def test_partial_output_and_interrupted_tools_do_not_complete():
    value, output, _ = parser()
    feed(value, init_frame(), step_frame("tool", "ACTIVE", tool_name="view_file",
                                        tool_info={"name": "view_file", "parameters": {}}))
    with pytest.raises(RuntimeError, match="without a successful"):
        value.finish()
    value.abort(TimeoutError("expired"))
    assert output[-1]["status"] == "failed" and not value.events.started


def test_adapter_resumes_only_owned_id_and_stdin_supports_long_text(tmp_path, monkeypatch):
    runs = []
    monkeypatch.setattr("src.harness.adapters.antigravity.command_argv", lambda _: ["agy"])
    def run(argv, **kwargs):
        runs.append(argv)
        content = json.loads(kwargs["stdin"])["message"]["content"]
        assert content == "x" * 40000
        assert "--continue" not in argv and "--dangerously-skip-permissions" not in argv and "-p" not in argv
        for frame in [init_frame(), step_frame(text_delta="hello"), result_frame()]:
            kwargs["on_line"](json.dumps(frame))
    monkeypatch.setattr("src.harness.adapters.antigravity.run_process", run)
    for _ in range(2):
        assert Adapter().run("x" * 40000, context(tmp_path)).text == "hello"
    assert "--conversation" not in runs[0]
    assert runs[1][runs[1].index("--conversation") + 1] == "session-one"
    new_cwd = tmp_path / "different"
    new_cwd.mkdir()
    with pytest.raises(ValueError, match="working directory changed"):
        Adapter().run("x", context(tmp_path, working_path=str(new_cwd)))
    assert len(runs) == 2


@pytest.mark.parametrize("enabled", [False, True])
def test_node_permission_choice_controls_process_and_overrides_stale_context(tmp_path, monkeypatch, enabled):
    (tmp_path / "config.json").write_text(json.dumps({"native_auto_approve": enabled}), encoding="utf-8")
    monkeypatch.setattr("src.harness.adapters.antigravity.command_argv", lambda _: ["agy"])
    runs = []

    def run(argv, **kwargs):
        runs.append(argv)
        for frame in [init_frame(), result_frame()]:
            kwargs["on_line"](json.dumps(frame))

    monkeypatch.setattr("src.harness.adapters.antigravity.run_process", run)
    assert Adapter().run("hello", context(tmp_path, native_auto_approve=not enabled)).text == "hello"
    assert len(runs) == 1
    assert ("--dangerously-skip-permissions" in runs[0]) is enabled
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8")) == {"native_auto_approve": enabled}


def test_model_catalog_preserves_exact_ids_and_rejects_unstructured_text(monkeypatch):
    from src.harness import antigravity_catalog as catalog
    monkeypatch.setattr(catalog, "command_argv", lambda _: ["agy"])
    monkeypatch.setattr(catalog, "run_process", lambda *a, **k: "gemini-4-argon-high\tGemini 4 Argon (High)\n")
    assert catalog.list_models() == ["gemini-4-argon-high"]
    monkeypatch.setattr(catalog, "run_process", lambda *a, **k: "login required\n")
    with pytest.raises(ValueError, match="invalid model catalog"):
        catalog.list_models()


def test_native_install_verifies_hash_before_replacing_binary(tmp_path, monkeypatch):
    from src.harness import antigravity_installation as install
    from src.providers.curl_types import CurlResponse
    old = install.binary(tmp_path)
    old.write_bytes(b"working version")
    monkeypatch.setattr(install, "release", lambda: {"version": "1.4.0", "url": "https://example.test/ag", "sha512": "0" * 128})
    monkeypatch.setattr(install.CurlHttpTransport, "request", lambda *a, **k: CurlResponse("bad", 200))
    with pytest.raises(ValueError, match="SHA512"):
        install.mutate(tmp_path, "install")
    assert old.read_bytes() == b"working version"
    monkeypatch.setattr(install, "release", lambda: {"version": "1.4.0", "url": "https://example.test/ag", "sha512": hashlib.sha512(b"new").hexdigest()})
    monkeypatch.setattr(install.CurlHttpTransport, "request", lambda *a, **k: CurlResponse("new", 200))
    monkeypatch.setattr(install, "version", lambda *a: "1.4.0")
    install.mutate(tmp_path, "install")
    assert old.read_bytes() == b"new"


def test_external_native_install_is_not_removed(tmp_path, monkeypatch):
    from src.harness import antigravity_installation as install
    monkeypatch.setattr(install.shutil, "which", lambda _: "C:/external/agy.exe")
    with pytest.raises(ValueError, match="owned by AgentPark"):
        install.mutate(tmp_path, "uninstall")
    with pytest.raises(ValueError, match="already installed externally"):
        install.mutate(tmp_path, "install")


def test_native_catalog_api_requires_owner_and_preserves_native_errors(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.web_backend.core import BackendCore
    from src.web_backend.route_registry import ApiRouteRegistry
    from src.harness import antigravity_catalog
    app = FastAPI()
    ApiRouteRegistry.register(app, BackendCore())
    monkeypatch.setattr(antigravity_catalog, "list_models", lambda: [DEFAULT_MODEL])
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        assert client.get("/api/harnesses/antigravity/models").json() == {"models": [DEFAULT_MODEL]}
        assert client.get("/api/harnesses/unknown/models").status_code == 404
        def failed():
            raise RuntimeError("authentication required")
        monkeypatch.setattr(antigravity_catalog, "list_models", failed)
        response = client.get("/api/harnesses/antigravity/models")
        assert response.status_code == 502 and "authentication required" in response.text
    with TestClient(app, client=("203.0.113.8", 12345)) as client:
        assert client.get("/api/harnesses/antigravity/models").status_code == 403
