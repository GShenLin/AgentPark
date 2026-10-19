from __future__ import annotations

import json
from pathlib import Path

import pytest

from nodes.opencode_node import Node
from src.harness.adapters.opencode import Adapter
from src.harness.adapters.opencode_config import DEFAULT_MODEL, load_request, select_option
from src.harness.contracts import HarnessContext
from src.harness.acp_events import AcpEvents
from src.harness.events import HarnessEvents
from src.harness.memory_reset import clear_harness_memory


def context(tmp_path, **values):
    return HarnessContext(str(tmp_path / "config.json"), str(tmp_path), values)


def control(model=DEFAULT_MODEL):
    return {"sessionId": "session-one", "configOptions": [
        {"id": "model", "type": "select", "options": [{"value": model}]},
        {"id": "mode", "type": "select", "options": [{"value": "build"}]},
    ]}


def test_native_schema_and_state_do_not_require_an_agentpark_provider(tmp_path):
    schema = Node().get_config_schema({"provider_id": "nonexistent"})
    assert "provider_id" not in schema and "model" not in schema
    request = load_request(context(tmp_path))
    assert request.model == DEFAULT_MODEL
    assert Path(request.cwd) == tmp_path / ".harness/opencode/workspace"
    assert load_request(context(tmp_path, native_model="other/model")).state_dir == request.state_dir
    (request.state_dir / "sessions.db").write_bytes(b"native memory")
    (Path(request.cwd) / "keep.txt").write_text("user work", encoding="utf-8")
    clear_harness_memory(str(tmp_path), {"type_id": "opencode_node"})
    assert not request.state_dir.exists()
    assert (Path(request.cwd) / "keep.txt").read_text() == "user work"


@pytest.mark.parametrize("values,match", [
    ({"access_role": "nondeveloper"}, "developer access"),
    ({"native_model": ""}, "provider/model"),
    ({"native_model": "model"}, "provider/model"),
    ({"native_model": "p/m\nx"}, "provider/model"),
    ({"native_agent": ""}, "native_agent"),
    ({"native_effort": []}, "must be strings"),
    ({"timeout_seconds": False}, "timeout_seconds"),
    ({"timeout_seconds": float("nan")}, "timeout_seconds"),
    ({"working_path": "Z:/missing-opencode-workspace"}, "does not exist"),
])
def test_invalid_native_requests_fail_before_launch(tmp_path, values, match):
    with pytest.raises(ValueError, match=match):
        load_request(context(tmp_path, **values))


def test_model_selection_never_substitutes_an_unavailable_free_model():
    with pytest.raises(ValueError, match="unavailable"):
        select_option(control("opencode/deepseek-v4.1-flash"), "model", DEFAULT_MODEL)
    grouped = {"configOptions": [{"id": "model", "type": "select", "options": [
        {"group": "opencode", "options": [{"value": DEFAULT_MODEL}]}]}]}
    assert select_option(grouped, "model", DEFAULT_MODEL) == DEFAULT_MODEL
    grouped["configOptions"][0]["options"].append({"value": DEFAULT_MODEL})
    with pytest.raises(ValueError, match="unavailable"):
        select_option(grouped, "model", DEFAULT_MODEL)


def test_adapter_resumes_native_db_and_closes_on_failure(tmp_path, monkeypatch):
    clients = []

    class FakeClient:
        def __init__(self, argv, **kwargs):
            self.kwargs, self.methods, self.closed = kwargs, [], False
            clients.append(self)
            assert argv == ["official-opencode", "acp"]

        def request(self, method, params):
            self.methods.append((method, params))
            if method == "initialize":
                return {"protocolVersion": 1, "agentCapabilities": {"sessionCapabilities": {"resume": {}, "close": {}}}}
            if method in {"session/new", "session/resume", "session/set_config_option"}:
                return control()
            if method == "session/prompt":
                self.kwargs["on_update"]({"sessionId": "session-one", "update": {
                    "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "OK"}}})
                return {"stopReason": "end_turn"}
            assert method == "session/close"
            return {}

        def close(self):
            self.closed = True

    monkeypatch.setattr("src.harness.adapters.opencode.AcpClient", FakeClient)
    monkeypatch.setattr("src.harness.adapters.opencode.command_argv", lambda _: ["official-opencode"])
    for _ in range(2):
        assert Adapter().run("hello", context(tmp_path)).text == "OK"
    assert clients[0].closed and clients[1].closed
    assert clients[0].kwargs["env"]["OPENCODE_DB"] == clients[1].kwargs["env"]["OPENCODE_DB"]
    assert "session/new" in [m for m, _ in clients[0].methods]
    assert "session/resume" in [m for m, _ in clients[1].methods]
    with pytest.raises(ValueError, match="unavailable"):
        Adapter().run("hello", context(tmp_path, native_model="opencode/missing-free"))
    assert clients[-1].closed
    assert "session/prompt" not in [m for m, _ in clients[-1].methods]
    with pytest.raises(ValueError, match="working directory changed"):
        Adapter().run("hello", context(tmp_path, working_path=str(tmp_path)))
    assert len(clients) == 3


def test_tool_output_keeps_visible_content_even_when_raw_output_only_has_metadata():
    parser = AcpEvents(HarnessEvents("opencode", "opencode", None))
    parser.bind("s")
    for update in [
        {"sessionUpdate": "tool_call", "toolCallId": "t", "title": "read", "status": "pending"},
        {"sessionUpdate": "tool_call_update", "toolCallId": "t", "status": "completed",
         "rawOutput": {"metadata": {"truncated": False}},
         "content": [{"type": "content", "content": {"type": "text", "text": "FILE_CONTENT"}}]},
    ]:
        parser.handle({"sessionId": "s", "update": update})
    assert "FILE_CONTENT" in parser.events.tools["t"]["result_preview"]


def test_catalog_is_native_and_strict(monkeypatch, tmp_path):
    import src.harness.opencode_catalog as catalog
    from contextlib import nullcontext
    monkeypatch.setattr(catalog, "runtime_lease", lambda _: nullcontext())
    monkeypatch.setattr(catalog, "install_root", lambda _: tmp_path)
    monkeypatch.setattr(catalog, "command_argv", lambda _: ["official-opencode"])
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return DEFAULT_MODEL + "\n"
    monkeypatch.setattr(catalog, "run_process", run)
    assert catalog.list_models() == [DEFAULT_MODEL]
    assert calls == [["official-opencode", "models", "--standalone"]]
    for invalid in ("", "banner\n" + DEFAULT_MODEL, DEFAULT_MODEL + "\n" + DEFAULT_MODEL):
        monkeypatch.setattr(catalog, "run_process", lambda *a, **k: invalid)
        with pytest.raises(ValueError, match="invalid model catalog"):
            catalog.list_models()


def test_catalog_endpoint_is_owner_only(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.web_backend.core import BackendCore
    from src.web_backend.route_registry import ApiRouteRegistry
    app = FastAPI()
    ApiRouteRegistry.register(app, BackendCore())
    monkeypatch.setattr("src.harness.opencode_catalog.list_models", lambda: [DEFAULT_MODEL])
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        assert client.get("/api/harnesses/opencode/models").json() == {"models": [DEFAULT_MODEL]}
    with TestClient(app, client=("192.0.2.1", 12345)) as client:
        assert client.get("/api/harnesses/opencode/models").status_code == 403
