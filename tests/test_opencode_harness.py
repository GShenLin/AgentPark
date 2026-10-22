from __future__ import annotations

import json
from pathlib import Path

import pytest

from nodes.opencode_node import Node
from src.harness.adapters.opencode import Adapter
from src.harness.adapters.opencode_config import RUNTIME_MODEL as DEFAULT_MODEL, select_option
from src.harness.config import load_cli_request
from src.harness.contracts import HarnessContext
from src.harness.acp_events import AcpEvents
from src.harness.events import HarnessEvents
from src.harness.memory_reset import clear_harness_memory


def context(tmp_path, **values):
    return HarnessContext(str(tmp_path / "config.json"), str(tmp_path), {"provider_id": "test-provider", "model": "selected-model", **values})


def control(model=DEFAULT_MODEL):
    return {"sessionId": "session-one", "configOptions": [
        {"id": "model", "type": "select", "options": [{"value": model}]},
        {"id": "mode", "type": "select", "options": [{"value": "build"}]},
    ]}


@pytest.fixture(autouse=True)
def provider_config(monkeypatch):
    monkeypatch.setattr("src.config_loader.ConfigLoader.get_provider_config", lambda self, key: {
        "id": key, "type": "openai", "supportmode": ["chat"], "model": "selected-model",
        "models": ["selected-model", "other"], "baseUrl": "http://localhost:9/v1", "apiKey": "unused"})


def test_shared_provider_schema_and_reset_preserve_workspace(tmp_path):
    schema = Node().get_config_schema({"provider_id": "test-provider"})
    assert "provider_id" in schema and "model" in schema and "native_model" not in schema
    request = load_cli_request("opencode", context(tmp_path))
    assert request.binding.model_id == "selected-model"
    assert load_cli_request("opencode", context(tmp_path, model="other")).state_dir == request.state_dir
    work = Path(request.cwd) / "keep.txt"
    work.write_text("user work", encoding="utf-8")
    clear_harness_memory(str(tmp_path), {"type_id": "opencode_node"})
    assert not request.state_dir.exists() and work.read_text() == "user work"


@pytest.mark.parametrize("values", [
    {"provider_id": ""}, {"access_role": "nondeveloper"},
    {"timeout_seconds": False}, {"timeout_seconds": float("nan")},
    {"working_path": "Z:/missing-harness-workspace"},
])
def test_invalid_request_never_launches(tmp_path, values):
    with pytest.raises(ValueError):
        load_cli_request("opencode", context(tmp_path, **values))


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
            self.on_update = kwargs["on_update"]
            clients.append(self)
            assert argv == ["official-opencode", "acp"]

        def request(self, method, params):
            self.methods.append((method, params))
            if method == "initialize":
                return {"protocolVersion": 1, "agentCapabilities": {"sessionCapabilities": {"resume": {}, "close": {}}}}
            if method in {"session/new", "session/resume", "session/set_config_option"}:
                return control()
            if method == "session/prompt":
                self.on_update({"sessionId": "session-one", "update": {
                    "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "OK"}}})
                return {"stopReason": "end_turn"}
            assert method == "session/close"
            return {}

        def is_alive(self):
            return not self.closed

        def reset(self, timeout, cancel_source):
            pass

        def close(self):
            self.closed = True

    monkeypatch.setattr("src.harness.adapters.opencode.AcpClient", FakeClient)
    monkeypatch.setattr("src.harness.adapters.resident.command_argv", lambda _: ["official-opencode"])
    adapter = Adapter()
    adapter.prepare(context(tmp_path))
    assert "session/prompt" not in [m for m, _ in clients[0].methods]
    for _ in range(2):
        assert adapter.run("hello", context(tmp_path)).text == "OK"
    assert len(clients) == 1 and not clients[0].closed
    assert "session/close" not in [m for m, _ in clients[0].methods]
    adapter.close()
    assert adapter.run("hello", context(tmp_path)).text == "OK"
    adapter.close()
    assert clients[0].closed and clients[1].closed
    assert clients[0].kwargs["env"]["OPENCODE_DB"] == clients[1].kwargs["env"]["OPENCODE_DB"]
    assert "session/new" in [m for m, _ in clients[0].methods]
    assert "session/resume" in [m for m, _ in clients[1].methods]
    with pytest.raises(ValueError, match="unavailable"):
        Adapter().run("hello", context(tmp_path, agent_mode="unavailable-agent"))
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
