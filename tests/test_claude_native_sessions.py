from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from claude_agent_sdk import SDKSessionInfo

from nodes.claude_node.runtime.session_state import read_selected_session_id
from src.web_backend.cli_session_runtime import CliSessionRuntime


SESSION_ID = "019c0000-0000-7000-8000-000000000002"


class _FakeClaudeManager:
    def __init__(self, cwd: str) -> None:
        self.cwd = cwd
        self.closed: list[str] = []

    def list_sessions(self, cwd: str):
        assert cwd == self.cwd
        return [
            SDKSessionInfo(
                session_id=SESSION_ID,
                summary="Native Claude history",
                last_modified=1784800010000,
                custom_title=None,
                first_prompt="Read setup.py",
                cwd=cwd,
                created_at=1784800000000,
            )
        ]

    def get_session_info(self, cwd: str, session_id: str):
        assert session_id == SESSION_ID
        return self.list_sessions(cwd)[0]

    def read_session(self, cwd: str, session_id: str):
        assert cwd == self.cwd
        assert session_id == SESSION_ID
        return [
            SimpleNamespace(
                type="user",
                uuid="user-1",
                message={"role": "user", "content": "Read setup.py"},
            ),
            SimpleNamespace(
                type="assistant",
                uuid="assistant-1",
                message={
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call-1",
                            "name": "Read",
                            "input": {"file_path": "setup.py"},
                        }
                    ],
                },
            ),
            SimpleNamespace(
                type="user",
                uuid="user-2",
                message={
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call-1",
                            "content": "contents",
                        }
                    ],
                },
            ),
            SimpleNamespace(
                type="assistant",
                uuid="assistant-2",
                message={"role": "assistant", "content": "Claude response"},
            ),
        ]

    def close_session(self, runtime_key: str):
        self.closed.append(runtime_key)


def _runtime(node_dir: Path, manager: _FakeClaudeManager, monkeypatch) -> CliSessionRuntime:
    class GraphRuntime:
        @staticmethod
        def _sanitize_graph_id(_graph_id):
            return "default"

        @staticmethod
        def _resolve_existing_node_id(_graph_id, _node_id):
            return "Claude"

        @staticmethod
        def _node_config_path(_node_id, _graph_id):
            return str(node_dir / "config.json")

        @staticmethod
        def _node_memory_path(_node_id, _graph_id):
            return str(node_dir / "memory.md")

        @staticmethod
        def _node_messages_path(_node_id, _graph_id):
            return str(node_dir / "messages.jsonl")

    host = SimpleNamespace(
        graph_runtime=GraphRuntime(),
        core=SimpleNamespace(node_live_outputs=SimpleNamespace(clear=lambda *_args: None)),
    )
    monkeypatch.setattr(
        "src.web_backend.cli_session_runtime.ClaudeSessionManager.instance",
        lambda: manager,
    )
    return CliSessionRuntime(host)


def test_cli_session_runtime_lists_and_selects_native_claude_history(monkeypatch, tmp_path):
    node_dir = tmp_path / "Claude"
    node_dir.mkdir()
    (node_dir / "config.json").write_text(
        json.dumps(
            {
                "node_id": "Claude",
                "type_id": "claude_node",
                "state": "idle",
                "working_path": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    manager = _FakeClaudeManager(str(tmp_path))
    runtime = _runtime(node_dir, manager, monkeypatch)

    listed = runtime.list_cli_sessions("Claude", "default")
    assert listed["supported"] is True
    assert listed["session_kind"] == "claude"
    assert listed["session_label"] == "Claude"
    assert listed["sessions"][0]["id"] == SESSION_ID
    assert listed["sessions"][0]["title"] == "Native Claude history"

    selected = runtime.select_cli_session(
        "Claude",
        {"session_id": SESSION_ID},
        "default",
    )

    assert selected["active_session_id"] == SESSION_ID
    assert read_selected_session_id(str(node_dir / "claude_session.json")) == SESSION_ID
    records = [
        json.loads(line)
        for line in (node_dir / "messages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [record["role"] for record in records] == ["user", "tool", "assistant"]
    assert records[1]["parts"][0]["name"] == "Read"
    assert records[1]["parts"][0]["result_preview"] == "contents"
    assert manager.closed
