from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nodes.antigravity_node import Node
from src.harness.adapters.antigravity import Adapter
from src.harness.adapters.antigravity_config import execution_options, RUNTIME_MODEL as DEFAULT_MODEL
from src.harness.config import load_cli_request
from src.harness.adapters.antigravity_events import AntigravityEvents
from src.harness.contracts import HarnessContext
from src.harness.events import HarnessEvents
from src.harness.memory_reset import clear_harness_memory


def context(tmp_path, **values):
    return HarnessContext(str(tmp_path / "config.json"), str(tmp_path), {"provider_id": "test-provider", "model": "selected-model", **values})


@pytest.fixture(autouse=True)
def provider_config(monkeypatch):
    monkeypatch.setattr("src.config_loader.ConfigLoader.get_provider_config", lambda self, key: {
        "id": key, "type": "openai", "supportmode": ["chat"], "model": "selected-model",
        "models": ["selected-model", "other"], "baseUrl": "http://localhost:9/v1", "apiKey": "unused"})


def test_shared_provider_schema_and_reset_preserve_workspace(tmp_path):
    schema = Node().get_config_schema({"provider_id": "test-provider"})
    assert "provider_id" in schema and "model" in schema and "native_model" not in schema
    request = load_cli_request("antigravity", context(tmp_path))
    assert request.binding.model_id == "selected-model"
    assert load_cli_request("antigravity", context(tmp_path, model="other")).state_dir == request.state_dir
    work = Path(request.cwd) / "keep.txt"
    work.write_text("user work", encoding="utf-8")
    clear_harness_memory(str(tmp_path), {"type_id": "antigravity_node"})
    assert not request.state_dir.exists() and work.read_text() == "user work"


@pytest.mark.parametrize("values", [
    {"provider_id": ""}, {"access_role": "nondeveloper"},
    {"timeout_seconds": False}, {"timeout_seconds": float("nan")},
    {"working_path": "Z:/missing-harness-workspace"},
])
def test_invalid_request_never_launches(tmp_path, values):
    with pytest.raises(ValueError):
        load_cli_request("antigravity", context(tmp_path, **values))


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


class FakeResidentAntigravity:
    instances = []

    def __init__(self, argv, **kwargs):
        self.argv, self.frames, self.closed, self.sent = argv, [init_frame()], False, []
        self.instances.append(self)

    def send(self, frame):
        self.sent.append(frame)
        self.frames.extend([step_frame(text_delta="hello"), result_frame()])

    def receive(self):
        return self.frames.pop(0)

    def reset(self, timeout, cancel_source):
        pass

    def is_alive(self):
        return not self.closed

    def close(self):
        self.closed = True


def test_adapter_resumes_only_owned_id_and_stdin_supports_long_text(tmp_path, monkeypatch):
    FakeResidentAntigravity.instances = []
    monkeypatch.setattr("src.harness.adapters.resident.command_argv", lambda _: ["agy"])
    monkeypatch.setattr("src.harness.adapters.antigravity.JsonlProcess", FakeResidentAntigravity)
    adapter = Adapter()
    adapter.prepare(context(tmp_path))
    first = FakeResidentAntigravity.instances[0]
    assert not first.sent
    for _ in range(2):
        assert adapter.run("x" * 40000, context(tmp_path)).text == "hello"
    assert len(FakeResidentAntigravity.instances) == 1
    assert not first.closed
    assert all(frame["message"]["content"] == "x" * 40000 for frame in first.sent)
    assert "--continue" not in first.argv and "--dangerously-skip-permissions" not in first.argv
    adapter.close()
    assert adapter.run("again", context(tmp_path)).text == "hello"
    second = FakeResidentAntigravity.instances[1]
    assert second.argv[second.argv.index("--conversation") + 1] == "session-one"
    adapter.close()
    new_cwd = tmp_path / "different"
    new_cwd.mkdir()
    with pytest.raises(ValueError, match="working directory changed"):
        adapter.run("x", context(tmp_path, working_path=str(new_cwd)))
    assert len(FakeResidentAntigravity.instances) == 2


@pytest.mark.parametrize("enabled", [False, True])
def test_node_permission_choice_controls_process_and_overrides_stale_context(tmp_path, monkeypatch, enabled):
    (tmp_path / "config.json").write_text(json.dumps({"native_auto_approve": enabled}), encoding="utf-8")
    FakeResidentAntigravity.instances = []
    monkeypatch.setattr("src.harness.adapters.resident.command_argv", lambda _: ["agy"])
    monkeypatch.setattr("src.harness.adapters.antigravity.JsonlProcess", FakeResidentAntigravity)
    adapter = Adapter()
    assert adapter.run("hello", context(tmp_path, native_auto_approve=not enabled)).text == "hello"
    assert ("--dangerously-skip-permissions" in adapter.client.argv) is enabled
    adapter.close()
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8")) == {"native_auto_approve": enabled}


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


@pytest.mark.parametrize("values", [{"native_mode": "invalid"}, {"native_auto_approve": "true"}, {"native_auto_approve": 1}])
def test_invalid_permissions(values, tmp_path):
    with pytest.raises(ValueError):
        execution_options(context(tmp_path, **values))
