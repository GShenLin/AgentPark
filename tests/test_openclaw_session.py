from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from src.harness.config import CliRunRequest
from src.harness.openclaw_session import OpenClawSessions
from src.harness.provider_binding import ProviderBinding


class Gateway:
    def __init__(self):
        self.active, self.released = {}, []
        self.next_id = 0

    def register(self, provider, **options):
        self.next_id += 1
        token = str(self.next_id)
        self.active[token] = (provider, options)
        return SimpleNamespace(token=token, base_url="http://127.0.0.1:12345/v1")

    def release(self, token):
        self.released.append(token)
        del self.active[token]


class Child:
    def __init__(self, argv, **kwargs):
        self.argv, self.kwargs = argv, kwargs
        self.alive, self.fail, self.turns = True, False, []

    def is_alive(self):
        return self.alive

    def run(self, params, **kwargs):
        self.turns.append(params)
        if self.fail:
            raise RuntimeError("broken turn")
        return {"payloads": [{"text": "ok"}]}

    def close(self):
        self.alive = False


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(ProviderBinding, "request_config", lambda self: {})
    gateway, children = Gateway(), []

    def factory(*args, **kwargs):
        child = Child(*args, **kwargs)
        children.append(child)
        return child

    sessions = OpenClawSessions(gateway=gateway, client_factory=factory)
    request = CliRunRequest(ProviderBinding("p", "model", "chat"), str(tmp_path), "", 10, tmp_path, None)
    return sessions, request, gateway, children


def run(sessions, request):
    return sessions.run(request, ["node", "openclaw.mjs"], "hello", None)


def test_same_conversation_reuses_process_without_rewriting_config(runtime):
    sessions, request, gateway, children = runtime
    run(sessions, request)
    path = request.state_dir / "openclaw.json"
    before = path.stat().st_mtime_ns
    run(sessions, request)
    assert len(children) == 1 and len(gateway.active) == 1
    assert path.stat().st_mtime_ns == before
    first, second = children[0].turns
    assert first["sessionId"] == second["sessionId"]
    assert first["idempotencyKey"] != second["idempotencyKey"]
    config = json.loads(path.read_text())
    assert config["gateway"]["bind"] == "loopback"
    assert config["gateway"]["auth"]["token"] == "${AGENTPARK_OPENCLAW_TOKEN}"
    assert "plugins" not in config
    assert config["agents"]["defaults"]["heartbeat"]["every"] == "0m"


def test_binding_change_releases_child_and_lease_but_preserves_native_session(runtime):
    sessions, request, gateway, children = runtime
    run(sessions, request)
    run(sessions, replace(request, binding=ProviderBinding("other", "next", "responses")))
    assert len(children) == 2 and not children[0].alive
    assert gateway.released == ["1"] and len(gateway.active) == 1
    assert children[0].turns[0]["sessionId"] == children[1].turns[0]["sessionId"]


def test_failed_turn_closes_tree_and_does_not_replay(runtime):
    sessions, request, gateway, children = runtime
    run(sessions, request)
    children[0].fail = True
    with pytest.raises(RuntimeError, match="broken turn"):
        run(sessions, request)
    assert len(children) == 1 and not children[0].alive and not gateway.active
    run(sessions, request)
    assert len(children) == 2


def test_memory_reset_and_upgrade_release_resources(runtime, tmp_path):
    sessions, request, gateway, children = runtime
    run(sessions, request)
    sessions.close_under(tmp_path / "unrelated")
    assert children[0].alive
    sessions.close_under(tmp_path)
    assert not children[0].alive and not gateway.active
    run(sessions, request)
    sessions.close_all()
    assert not children[1].alive and not gateway.active
