import pytest

from src.harness import opencode_options as catalog


def controls(effort=False):
    values = {"mode": ["build", "plan"], "model": ["p/free", "p/other"]}
    if effort:
        values["effort"] = ["low", "high"]
    return {"sessionId": "discovery", "configOptions": [
        {"id": key, "type": "select", "options": [{"value": x, "name": x.upper()} for x in choices]}
        for key, choices in values.items()]}


def test_discovery_uses_selected_model_and_ephemeral_session(tmp_path, monkeypatch):
    calls, databases, clients = [], [], []
    class Client:
        closed = False
        def __init__(self, argv, **kwargs):
            databases.append(kwargs["env"]["OPENCODE_DB"])
            clients.append(self)
        def request(self, method, params):
            calls.append((method, params))
            if method == "initialize":
                return {"protocolVersion": 1}
            return controls(effort=method == "session/set_config_option" and params["configId"] == "model")
        def close(self):
            self.closed = True
    monkeypatch.setattr(catalog, "AcpClient", Client)
    monkeypatch.setattr(catalog, "install_root", lambda _: tmp_path)
    monkeypatch.setattr(catalog, "command_argv", lambda _: ["opencode"])
    result = catalog.configuration_options(model="p/free", agent="plan")
    assert result["native_effort"] == [{"value": "low", "label": "LOW"}, {"value": "high", "label": "HIGH"}]
    assert [(p["configId"], p["value"]) for m, p in calls if m == "session/set_config_option"] == [("mode", "plan"), ("model", "p/free")]
    assert calls[-1][0] == "session/close" and clients[0].closed
    from pathlib import Path
    assert not Path(databases[0]).parent.exists()
    assert all(m not in {"session/prompt", "session/resume"} for m, _ in calls)
    calls.clear()
    missing = catalog.configuration_options(model="p/unavailable", agent="build")
    assert missing["selection_error"] and missing["native_effort"] == []
    assert missing["native_model"]
    assert not any(m == "session/set_config_option" and p["configId"] == "model" for m, p in calls)


def test_grouped_options_and_absent_effort():
    control = controls()
    assert catalog.options(control, "effort", optional=True) == []
    model = control["configOptions"][1]
    model["options"] = [{"group": "Provider", "options": model["options"]}]
    assert len(catalog.options(control, "model")) == 2
    model["options"].append({"value": "p/free", "name": "Duplicate"})
    with pytest.raises(ValueError, match="Duplicate"):
        catalog.options(control, "model")


def test_discovery_cleanup_waits_only_for_windows_sharing_violation(tmp_path, monkeypatch):
    calls = []
    original = catalog.tempfile.TemporaryDirectory.cleanup
    def cleanup(self):
        calls.append(self.name)
        if len(calls) == 1:
            error = PermissionError("SQLite mapping still open")
            error.winerror = 32
            raise error
        original(self)
    monkeypatch.setattr(catalog.tempfile.TemporaryDirectory, "cleanup", cleanup)
    with catalog.discovery_directory(tmp_path) as path:
        assert path.is_dir()
    assert len(calls) == 2 and not path.exists()
