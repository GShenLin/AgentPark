from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.codex_runtime.app_server_client import CodexAppServerClient
from src.codex_runtime.session_manager import CodexSessionManager
from src.codex_runtime.session_manager import CodexSessionSpec
from src.codex_runtime.thread_state import read_selected_thread_id
from src.codex_runtime.thread_state import write_selected_thread_id
from src.web_backend.codex_session_runtime import CodexSessionRuntime
from src.web_backend.node_execution_context import resolve_node_storage_paths


THREAD_ID = "019c0000-0000-7000-8000-000000000001"


def _write_config(node_dir: Path, *, node_type: str = "codex_node", state: str = "idle") -> None:
    node_dir.mkdir(parents=True, exist_ok=True)
    (node_dir / "config.json").write_text(
        json.dumps({
            "node_id": "Codex",
            "type_id": node_type,
            "state": state,
            "codex_command": "codex",
        }),
        encoding="utf-8",
    )


def _thread(*, include_turns: bool) -> dict:
    turns = []
    if include_turns:
        turns = [{
            "id": "turn-1",
            "startedAt": 1784800000,
            "completedAt": 1784800010,
            "items": [
                {
                    "type": "userMessage",
                    "id": "user-1",
                    "content": [{"type": "text", "text": "Native Codex history"}],
                },
                {
                    "type": "reasoning",
                    "id": "reasoning-1",
                    "summary": ["Inspect the project"],
                    "content": [],
                },
                {
                    "type": "commandExecution",
                    "id": "tool-1",
                    "command": "Get-ChildItem",
                    "cwd": "D:\\Project",
                    "status": "completed",
                    "aggregatedOutput": "Codex",
                    "durationMs": 12,
                },
                {
                    "type": "agentMessage",
                    "id": "assistant-1",
                    "text": "Native response",
                },
            ],
        }]
    return {
        "id": THREAD_ID,
        "name": "Native thread",
        "preview": "Native Codex history",
        "modelProvider": "openai",
        "createdAt": 1784800000,
        "updatedAt": 1784800010,
        "cwd": "D:\\Project",
        "source": "cli",
        "turns": turns,
    }


class _FakeManager:
    def __init__(self) -> None:
        self.closed: list[str] = []

    def list_threads(self, command: str) -> list[dict]:
        assert command == "codex"
        return [_thread(include_turns=False)]

    def read_thread(self, command: str, thread_id: str) -> dict:
        assert command == "codex"
        if thread_id != THREAD_ID:
            raise ValueError("thread not found")
        return _thread(include_turns=True)

    def close_session(self, runtime_key: str) -> None:
        self.closed.append(runtime_key)


def _runtime(node_dir: Path, manager: _FakeManager, monkeypatch) -> CodexSessionRuntime:
    class GraphRuntime:
        @staticmethod
        def _sanitize_graph_id(_graph_id):
            return "default"

        @staticmethod
        def _resolve_existing_node_id(_graph_id, _node_id):
            return "Codex"

        @staticmethod
        def _node_config_path(_node_id, _graph_id):
            return str(node_dir / "config.json")

        @staticmethod
        def _node_memory_path(_node_id, _graph_id):
            return str(node_dir / "memory.md")

        @staticmethod
        def _node_messages_path(_node_id, _graph_id):
            return str(node_dir / "messages.jsonl")

    live_outputs = SimpleNamespace(clear=lambda *_args: None)
    host = SimpleNamespace(
        graph_runtime=GraphRuntime(),
        core=SimpleNamespace(node_live_outputs=live_outputs),
    )
    monkeypatch.setattr(
        "src.web_backend.codex_session_runtime.CodexSessionManager.instance",
        lambda: manager,
    )
    return CodexSessionRuntime(host)


def test_thread_state_migrates_legacy_pointer_and_writes_current_contract(tmp_path):
    state_path = tmp_path / "codex_session.json"
    state_path.write_text(
        json.dumps({"version": 1, "signature": "legacy", "thread_id": THREAD_ID}),
        encoding="utf-8",
    )

    assert read_selected_thread_id(str(state_path)) == THREAD_ID

    write_selected_thread_id(str(state_path), "")
    assert read_selected_thread_id(str(state_path)) == ""
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "version": 2,
        "thread_id": "",
    }


def test_codex_and_regular_nodes_use_node_root_memory_paths(tmp_path):
    for name, node_type in (("Codex", "codex_node"), ("Agent", "agent_node")):
        node_dir = tmp_path / name
        _write_config(node_dir, node_type=node_type)
        paths = resolve_node_storage_paths(str(node_dir / "config.json"))
        assert paths == {
            "memory_path": str(node_dir / "memory.md"),
            "messages_path": str(node_dir / "messages.jsonl"),
        }


def test_app_server_native_thread_list_exhausts_pagination():
    client = object.__new__(CodexAppServerClient)
    calls = []

    def request(method, params, **_kwargs):
        calls.append((method, dict(params)))
        if "cursor" not in params:
            return {"data": [{"id": "a"}], "nextCursor": "next"}
        return {"data": [{"id": "b"}], "nextCursor": None}

    client.request = request

    assert client.list_threads() == [{"id": "a"}, {"id": "b"}]
    assert calls[0][1]["modelProviders"] == []
    assert calls[0][1]["sortKey"] == "updated_at"
    assert calls[1][1]["cursor"] == "next"


def test_session_manager_resumes_selected_native_thread_through_agentpark_provider(tmp_path):
    state_path = tmp_path / "codex_session.json"
    state_path.write_text(
        json.dumps({"version": 1, "signature": "old-provider", "thread_id": THREAD_ID}),
        encoding="utf-8",
    )
    captures = {}

    class Gateway:
        def register(self, provider_id):
            captures["provider_id"] = provider_id
            return SimpleNamespace(base_url="http://127.0.0.1:1234/v1", token="lease")

        def release(self, token):
            captures["released"] = token

        @staticmethod
        def observe_requests(_token, _observer):
            return nullcontext()

    class Client:
        def __init__(self, command):
            captures["command"] = command

        def request(self, method, params, **_kwargs):
            captures.setdefault("requests", []).append((method, params))
            assert method == "model/list"
            return {
                "data": [
                    {
                        "id": "runtime-default",
                        "model": "runtime-default",
                        "isDefault": True,
                        "supportedReasoningEfforts": [
                            {"reasoningEffort": "high", "description": "High"},
                        ],
                    }
                ],
                "nextCursor": None,
            }

        def start_thread(self, **kwargs):
            captures["start"] = kwargs
            return kwargs["resume_thread_id"] or "new-thread"

        def run_turn(self, thread_id, text, **_kwargs):
            captures["run"] = (thread_id, text)
            return "resumed"

        @staticmethod
        def is_alive():
            return True

        def close(self):
            captures["closed"] = True

    manager = CodexSessionManager(gateway=Gateway(), client_factory=Client)
    try:
        result = manager.run_turn(
            CodexSessionSpec(
                session_key="default|Codex",
                provider_id="provider-a",
                model="model-a",
                command="codex",
                cwd=str(tmp_path),
                sandbox="workspace-write",
                state_path=str(state_path),
            ),
            "continue",
        )
    finally:
        manager.close_all()

    assert result == "resumed"
    assert captures["provider_id"] == "provider-a"
    assert captures["start"]["resume_thread_id"] == THREAD_ID
    assert captures["start"]["model"] == "runtime-default"
    assert captures["start"]["model_provider"] == "agentpark"
    assert captures["start"]["provider_config"]["base_url"] == "http://127.0.0.1:1234/v1"
    assert captures["run"] == (THREAD_ID, "continue")
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "version": 2,
        "thread_id": THREAD_ID,
    }


def test_native_session_selection_projects_codex_history_to_memory(monkeypatch, tmp_path):
    node_dir = tmp_path / "Codex"
    _write_config(node_dir)
    manager = _FakeManager()
    runtime = _runtime(node_dir, manager, monkeypatch)

    initial = runtime.list_codex_sessions("Codex", "default")
    assert initial["is_new_session"] is True
    assert initial["sessions"][0]["id"] == THREAD_ID
    assert initial["sessions"][0]["source"] == "cli"

    selected = runtime.select_codex_session(
        "Codex",
        {"session_id": THREAD_ID},
        "default",
    )

    assert selected["active_session_id"] == THREAD_ID
    assert read_selected_thread_id(str(node_dir / "codex_session.json")) == THREAD_ID
    records = [
        json.loads(line)
        for line in (node_dir / "messages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [record["role"] for record in records] == ["user", "commentary", "tool", "assistant"]
    assert records[2]["parts"][0]["name"] == "shell_command"
    assert records[2]["parts"][0]["result_preview"] == "Codex"
    assert manager.closed

    new_session = runtime.select_codex_session("Codex", {"session_id": ""}, "default")
    assert new_session["is_new_session"] is True
    assert read_selected_thread_id(str(node_dir / "codex_session.json")) == ""
    assert (node_dir / "messages.jsonl").read_text(encoding="utf-8") == ""


def test_native_session_selection_rejects_switch_while_working(monkeypatch, tmp_path):
    node_dir = tmp_path / "Codex"
    _write_config(node_dir, state="working")
    runtime = _runtime(node_dir, _FakeManager(), monkeypatch)
    monkeypatch.setattr(
        "src.web_backend.codex_session_runtime._read_json_dict",
        lambda _path: {
            "node_id": "Codex",
            "type_id": "codex_node",
            "state": "working",
            "codex_command": "codex",
        },
    )

    with pytest.raises(Exception, match="Cannot switch Codex Session while the node is working"):
        runtime.select_codex_session("Codex", {"session_id": ""}, "default")


def test_codex_native_session_http_api(monkeypatch, tmp_path):
    import src.web_backend as backend
    from fastapi.testclient import TestClient

    manager = _FakeManager()
    monkeypatch.setattr(
        "src.web_backend.codex_session_runtime.CodexSessionManager.instance",
        lambda: manager,
    )
    runtime_root = str(tmp_path)
    original_get_runtime_root = backend._get_runtime_root
    original_get_resource_root = backend._get_resource_root
    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: original_get_runtime_root()
    try:
        node_dir = tmp_path / "memories" / "default" / "Codex"
        _write_config(node_dir)
        client = TestClient(backend.create_app())

        listed = client.get("/api/nodes/instances/Codex/codex-sessions?graph_id=default")
        assert listed.status_code == 200
        assert listed.json()["sessions"][0]["id"] == THREAD_ID

        selected = client.post(
            "/api/nodes/instances/Codex/codex-sessions/select?graph_id=default",
            json={"session_id": THREAD_ID},
        )
        assert selected.status_code == 200
        memory = client.get("/api/nodes/instances/Codex/memory?graph_id=default")
        assert memory.status_code == 200
        assert [record["role"] for record in memory.json()["messages"]] == [
            "user",
            "commentary",
            "tool",
            "assistant",
        ]
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root
