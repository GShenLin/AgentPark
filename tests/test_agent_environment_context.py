import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


def test_agent_environment_context_includes_only_stable_model_visible_fields(monkeypatch, tmp_path):
    import src.providers.agent_environment_context as module

    workspace = tmp_path / "workspace"
    working = workspace / "project"
    working.mkdir(parents=True)
    monkeypatch.setattr(module, "get_workspace_root", lambda: str(workspace))

    agent = SimpleNamespace(
        _aitools_working_path=str(working),
        _aitools_shell="powershell",
        _aitools_graph_id="graph-secret",
        _aitools_node_id="node-secret",
        config={
            "apiKey": "sk-secret",
            "tools": ["rg_search_text"],
            "provider_id": "openai",
        },
    )

    context = module.build_agent_environment_context(agent)

    assert set(context) == {"workspace_root", "working_path", "shell", "request_time"}
    assert context["workspace_root"] == str(workspace)
    assert context["working_path"] == str(working)
    assert context["shell"] == "powershell"
    assert "secret" not in json.dumps(context, ensure_ascii=False)
    assert "rg_search_text" not in json.dumps(context, ensure_ascii=False)


def test_agent_environment_context_handles_missing_optional_runtime_fields(monkeypatch, tmp_path):
    import src.providers.agent_environment_context as module

    monkeypatch.setattr(module, "get_workspace_root", lambda: str(tmp_path))

    context = module.build_agent_environment_context(SimpleNamespace(config={}))

    assert context["workspace_root"] == str(tmp_path)
    assert context["working_path"] == str(tmp_path)
    assert context["request_time"]
    assert context["shell"]


def test_agent_environment_context_request_time_is_regenerated(monkeypatch, tmp_path):
    import src.providers.agent_environment_context as module

    class Clock:
        value = datetime(2026, 6, 30, 9, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls):
            current = cls.value
            cls.value = current + timedelta(seconds=1)
            return current

    monkeypatch.setattr(module, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(module, "datetime", Clock)

    agent = SimpleNamespace(config={})

    first = module.build_agent_environment_context(agent)
    second = module.build_agent_environment_context(agent)

    assert first["request_time"] != second["request_time"]
    assert first["request_time"].startswith("2026-06-30T")
    assert second["request_time"].startswith("2026-06-30T")
