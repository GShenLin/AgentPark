"""Bridge protocol tests with a deterministic SDK double; real SDK coverage lives in smoke tests."""
from __future__ import annotations

import io
import json
import sys
from types import SimpleNamespace

import pytest

from src.harness.adapters import hermes_runner


def invoke(tmp_path, monkeypatch, result, *, existing=None, flush_results=(True, True), rotated_session=None,
           end_reason=None, reasoning_effort=""):
    if existing is not None:
        (tmp_path / "conversation.json").write_text(json.dumps(existing), encoding="utf-8")
    calls = []
    class Database:
        def __init__(self, *, db_path):
            self.path = db_path
            self.closed = False
            self.flushes = []
            self.reopened = []
        def get_session(self, session_id):
            return {"end_reason": end_reason} if existing else None
        def reopen_session(self, session_id):
            self.reopened.append(session_id)
        def close(self):
            self.closed = True

    flush_results = iter(flush_results)
    class Agent:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.session_id = kwargs["session_id"]
            self.db = kwargs["session_db"]
        def _flush_messages_to_session_db(self, messages):
            assert not self.db.closed
            self.db.flushes.append(list(messages))
            return next(flush_results)
        def run_conversation(self, **kwargs):
            assert self._end_session_on_close is False
            assert not self.db.closed
            calls.append(kwargs)
            print("native diagnostics must not corrupt stdout")
            if rotated_session:
                self.session_id = rotated_session
            return result
        def close(self):
            assert not self.db.closed
            calls.append("closed")
    output = io.StringIO()
    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(AIAgent=Agent))
    monkeypatch.setitem(sys.modules, "hermes_state", SimpleNamespace(SessionDB=Database))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "text": "hello", "model": "selected", "base_url": "http://127.0.0.1/new-lease",
        "instruction": "node instruction", "state_dir": str(tmp_path), "timeout": 60,
        "reasoning_effort": reasoning_effort,
    })))
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setenv("AGENTPARK_HARNESS_TOKEN", "temporary-token")
    return output, calls


def test_runner_rebinds_endpoint_and_atomically_saves_history(tmp_path, monkeypatch):
    existing = {"schema": 1, "session_id": "prior-session", "messages": [{"role": "user", "content": "prior"}]}
    result = {"completed": True, "final_response": "done", "messages": [*existing["messages"], {"role": "assistant", "content": "done"}]}
    output, calls = invoke(tmp_path, monkeypatch, result, existing=existing)
    hermes_runner.main()
    assert json.loads(output.getvalue()) == {"type": "result", "text": "done"}
    assert calls[0]["session_id"] == "prior-session"
    assert calls[0]["base_url"].endswith("new-lease")
    assert calls[0]["model"] == "selected"
    assert calls[0]["api_key"] == "temporary-token"
    assert calls[1]["conversation_history"] == existing["messages"]
    assert calls[-1] == "closed"
    db = calls[0]["session_db"]
    assert db.path == tmp_path / "home" / "state.db"
    assert db.flushes == [existing["messages"], result["messages"]]
    assert db.closed
    instruction = calls[0]["ephemeral_system_prompt"]
    assert instruction.startswith("node instruction\n\n")
    assert "excludes the current live session" in instruction
    state = json.loads((tmp_path / "conversation.json").read_text(encoding="utf-8"))
    assert state["messages"] == result["messages"]
    assert "temporary-token" not in json.dumps(state)


@pytest.mark.parametrize("effort", ["", "high", "max"])
def test_runner_passes_node_reasoning_effort_to_sdk(tmp_path, monkeypatch, effort):
    result = {"completed": True, "final_response": "done", "messages": []}
    output, calls = invoke(tmp_path, monkeypatch, result, reasoning_effort=effort)
    hermes_runner.main()
    assert calls[0]["reasoning_config"] == ({"enabled": True, "effort": effort} if effort else None)
    assert calls[0]["request_overrides"] == ({"reasoning": {"effort": effort}} if effort else None)


@pytest.mark.parametrize("failure", [
    {"completed": False, "failed": True, "error": "upstream error"},
    {"completed": False, "interrupted": True},
    {"completed": False, "turn_exit_reason": "budget_exhausted"},
    {"completed": True, "cleanup_errors": ["storage failure"]},
    {"completed": True, "messages": "invalid"},
])
def test_failed_turn_preserves_successful_conversation(tmp_path, monkeypatch, failure):
    existing = {"schema": 1, "session_id": "session", "messages": [{"role": "assistant", "content": "keep"}]}
    result = {"completed": True, "final_response": "partial", "messages": [], **failure}
    output, calls = invoke(tmp_path, monkeypatch, result, existing=existing)
    with pytest.raises(SystemExit) as error:
        hermes_runner.main()
    assert error.value.code == 1
    assert json.loads(output.getvalue())["type"] == "error"
    assert calls[-1] == "closed"
    assert calls[0]["session_db"].closed
    assert json.loads((tmp_path / "conversation.json").read_text(encoding="utf-8")) == existing


def test_corrupt_snapshot_is_not_silently_reset(tmp_path, monkeypatch):
    output, calls = invoke(tmp_path, monkeypatch, {}, existing={"messages": []})
    with pytest.raises(SystemExit):
        hermes_runner.main()
    assert not calls
    assert "Invalid Hermes conversation snapshot" in json.loads(output.getvalue())["message"]


@pytest.mark.parametrize("flush_results", [(False,), (True, False)])
def test_database_write_failure_is_reported_and_preserves_snapshot(tmp_path, monkeypatch, flush_results):
    existing = {"schema": 1, "session_id": "session", "messages": [{"role": "user", "content": "keep"}]}
    result = {"completed": True, "final_response": "done", "messages": [*existing["messages"],
                                                                            {"role": "assistant", "content": "done"}]}
    output, calls = invoke(tmp_path, monkeypatch, result, existing=existing, flush_results=flush_results)
    with pytest.raises(SystemExit):
        hermes_runner.main()
    assert "could not persist" in json.loads(output.getvalue())["message"]
    assert calls[-1] == "closed"
    assert calls[0]["session_db"].closed
    assert json.loads((tmp_path / "conversation.json").read_text(encoding="utf-8")) == existing
    if len(flush_results) == 1:
        assert len(calls) == 2  # Failure to restore history prevents inference.


def test_database_open_failure_never_starts_inference(tmp_path, monkeypatch):
    output, calls = invoke(tmp_path, monkeypatch, {})
    def unavailable(**kwargs):
        raise OSError("database unavailable")
    monkeypatch.setitem(sys.modules, "hermes_state", SimpleNamespace(SessionDB=unavailable))
    with pytest.raises(SystemExit):
        hermes_runner.main()
    assert not calls
    assert "database unavailable" in json.loads(output.getvalue())["message"]
    assert not (tmp_path / "conversation.json").exists()


def test_snapshot_follows_native_session_rotation(tmp_path, monkeypatch):
    result = {"completed": True, "final_response": "done", "messages": [{"role": "assistant", "content": "done"}]}
    output, calls = invoke(tmp_path, monkeypatch, result, rotated_session="compressed-session")
    hermes_runner.main()
    state = json.loads((tmp_path / "conversation.json").read_text(encoding="utf-8"))
    assert state["session_id"] == "compressed-session"
    assert calls[0]["session_db"].flushes == [result["messages"]]


@pytest.mark.parametrize("end_reason", ["agent_close", "compression", "session_reset", None])
def test_resume_only_reopens_process_closed_session(tmp_path, monkeypatch, end_reason):
    existing = {"schema": 1, "session_id": "prior", "messages": [{"role": "user", "content": "hello"}]}
    result = {"completed": True, "final_response": "done", "messages": [*existing["messages"],
                                                                            {"role": "assistant", "content": "done"}]}
    output, calls = invoke(tmp_path, monkeypatch, result, existing=existing, end_reason=end_reason)
    hermes_runner.main()
    assert calls[0]["session_db"].reopened == (["prior"] if end_reason == "agent_close" else [])
