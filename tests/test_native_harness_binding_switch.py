"""Existing Codex/Claude managers must also preserve identity when reconnecting."""
from contextlib import nullcontext
from types import SimpleNamespace

from claude_agent_sdk import ResultMessage

from nodes.claude_node.runtime.contracts import ClaudeSessionSpec
from nodes.claude_node.runtime.session_manager import ClaudeSessionManager
from nodes.codex_node.runtime.session_manager import CodexSessionManager, CodexSessionSpec


class Gateway:
    def __init__(self):
        self.bindings = []

    def register(self, provider_id, *, model, **kwargs):
        self.bindings.append((provider_id, model))
        return SimpleNamespace(base_url="http://127.0.0.1:1234/v1", token=str(len(self.bindings)))

    def release(self, token):
        pass

    def observe_requests(self, token, observer):
        return nullcontext()


BINDINGS = [("p", "first"), ("p", "second"), ("other", "second"), ("p", "first")]


def test_codex_binding_switches_resume_same_thread(tmp_path):
    starts = []
    turns = []

    class Client:
        def __init__(self, command):
            pass

        def request(self, method, params, **kwargs):
            assert method == "model/list"
            return {"data": [{"id": model, "model": model, "isDefault": index == 0,
                              "supportedReasoningEfforts": []}
                             for index, model in enumerate(["first", "second"])], "nextCursor": None}

        def start_thread(self, **kwargs):
            starts.append(kwargs)
            return kwargs["resume_thread_id"] or "existing-thread"

        def run_turn(self, thread_id, text, **kwargs):
            turns.append(thread_id)
            return "ok"

        def is_alive(self):
            return True

        def close(self):
            pass

    gateway = Gateway()
    manager = CodexSessionManager(gateway=gateway, client_factory=Client)
    try:
        for provider, model in BINDINGS:
            spec = CodexSessionSpec(session_key="node", provider_id=provider, model=model, command="codex",
                                    cwd=str(tmp_path), sandbox="workspace-write", state_path=str(tmp_path / "codex.json"))
            assert manager.run_turn(spec, "continue") == "ok"
    finally:
        manager.close_all()
    assert gateway.bindings == BINDINGS
    assert turns == ["existing-thread"] * 4
    assert all(start["resume_thread_id"] == "existing-thread" for start in starts[1:])
    assert [start["model"] for start in starts] == [model for _, model in BINDINGS]


def test_claude_binding_switches_resume_same_session(tmp_path):
    options = []

    class Client:
        def __init__(self, value):
            self.options = value
            options.append(value)

        async def connect(self):
            pass

        async def disconnect(self):
            pass

        async def query(self, text):
            pass

        async def receive_response(self):
            yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                                num_turns=1, session_id=self.options.resume or self.options.session_id, result="ok")

    gateway = Gateway()
    manager = ClaudeSessionManager(gateway=gateway, client_factory=Client)
    try:
        for provider, model in BINDINGS:
            spec = ClaudeSessionSpec(session_key="node", provider_id=provider, model=model, command="claude",
                                     cwd=str(tmp_path), permission_mode="default", state_path=str(tmp_path / "claude.json"))
            assert manager.run_turn(spec, "continue") == "ok"
    finally:
        manager.close_all()
    assert gateway.bindings == BINDINGS
    session_id = options[0].session_id
    assert session_id
    assert all(option.resume == session_id and option.session_id is None for option in options[1:])
    assert [option.model for option in options] == [model for _, model in BINDINGS]
