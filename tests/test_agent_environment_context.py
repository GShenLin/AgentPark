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
        _agentpark_workspace_root=str(workspace),
        _agentpark_working_path=str(working),
        _agentpark_shell="powershell",
        _agentpark_graph_id="graph-secret",
        _agentpark_node_id="node-secret",
        config={
            "apiKey": "sk-secret",
            "tools": ["rg_search_text"],
            "provider_id": "openai",
        },
    )

    context = module.build_agent_environment_context(agent)

    assert set(context) == {"workspace_path", "shell", "current_date", "timezone", "request_time"}
    assert context["workspace_path"] == str(working)
    assert context["shell"] == "powershell"
    assert context["workspace_path"] != str(workspace)
    assert "secret" not in json.dumps(context, ensure_ascii=False)
    assert "rg_search_text" not in json.dumps(context, ensure_ascii=False)


def test_agent_environment_context_handles_missing_optional_runtime_fields(monkeypatch, tmp_path):
    import src.providers.agent_environment_context as module

    monkeypatch.setattr(module, "get_workspace_root", lambda: str(tmp_path))

    context = module.build_agent_environment_context(SimpleNamespace(config={}))

    assert context["workspace_path"] == str(tmp_path)
    assert context["request_time"]
    assert context["shell"]


def test_format_agent_environment_context_filters_runtime_only_fields(tmp_path):
    import src.providers.agent_environment_context as module

    text = module.format_agent_environment_context(
        {
            "workspace_path": str(tmp_path),
            "working_path": str(tmp_path / "work"),
            "shell": "powershell",
            "current_date": "2026-06-30",
            "timezone": "Asia/Shanghai",
            "request_time": "2026-06-30T09:00:00+08:00",
        }
    )
    assert text.startswith("<environment_context>\n")
    assert text.endswith("\n</environment_context>")
    assert f"<cwd>{tmp_path}</cwd>" in text
    assert "<shell>powershell</shell>" in text
    assert "<current_date>2026-06-30</current_date>" in text
    assert "<timezone>Asia/Shanghai</timezone>" in text
    assert "2026-06-30T09:00:00+08:00" not in text
    assert "<filesystem>" in text
    assert "working_path" not in text


def test_agent_environment_context_maps_windows_timezone_to_iana(monkeypatch):
    import src.providers.agent_environment_context as module

    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(module, "_windows_timezone_name", lambda: "China Standard Time")

    assert module._resolve_timezone(datetime(2026, 7, 2, tzinfo=timezone.utc)) == "Asia/Shanghai"


def test_agent_environment_context_prefers_tz_environment(monkeypatch):
    import src.providers.agent_environment_context as module

    monkeypatch.setenv("TZ", "Asia/Shanghai")
    monkeypatch.setattr(module, "_windows_timezone_name", lambda: "Pacific Standard Time")

    assert module._resolve_timezone(datetime(2026, 7, 2, tzinfo=timezone.utc)) == "Asia/Shanghai"


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


def test_resolve_agent_relative_path_uses_working_path_for_relative_paths(tmp_path):
    import src.providers.agent_environment_context as module

    working = tmp_path / "work"
    working.mkdir()
    agent = SimpleNamespace(_agentpark_working_path=str(working))

    assert module.resolve_agent_relative_path("src/app.py", agent=agent) == str(working / "src" / "app.py")


def test_resolve_agent_relative_path_preserves_absolute_paths(tmp_path):
    import src.providers.agent_environment_context as module

    working = tmp_path / "work"
    absolute = tmp_path / "outside.txt"
    working.mkdir()
    agent = SimpleNamespace(_agentpark_working_path=str(working))

    assert module.resolve_agent_relative_path(str(absolute), agent=agent) == str(absolute)


def test_resolve_agent_relative_path_rejects_missing_working_path(tmp_path):
    import pytest
    import src.providers.agent_environment_context as module

    missing = tmp_path / "missing"
    agent = SimpleNamespace(_agentpark_working_path=str(missing))

    with pytest.raises(ValueError, match="WorkingPath directory does not exist"):
        module.resolve_agent_relative_path("relative.txt", agent=agent)


def test_resolve_agent_relative_path_uses_graph_working_path_when_node_unset(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace
    import src.providers.agent_environment_context as module
    import src.web_backend.runtime_paths as runtime_paths

    graph_work = tmp_path / "graph-work"
    graph_work.mkdir()
    runtime_root = tmp_path / "runtime"
    graph_dir = runtime_root / "memories" / "g1"
    graph_dir.mkdir(parents=True)
    (graph_dir / "config.json").write_text(
        json.dumps({"id": "g1", "name": "g1", "working_path": str(graph_work), "output_routes": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(runtime_root))

    agent = SimpleNamespace(_agentpark_graph_id="g1", config={})

    assert module.resolve_agent_relative_path("src/app.py", agent=agent) == str(graph_work / "src" / "app.py")


def test_resolve_agent_relative_path_prefers_node_working_path_over_graph(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace
    import src.providers.agent_environment_context as module
    import src.web_backend.runtime_paths as runtime_paths

    node_work = tmp_path / "node-work"
    graph_work = tmp_path / "graph-work"
    node_work.mkdir()
    graph_work.mkdir()
    runtime_root = tmp_path / "runtime"
    graph_dir = runtime_root / "memories" / "g1"
    graph_dir.mkdir(parents=True)
    (graph_dir / "config.json").write_text(
        json.dumps({"id": "g1", "name": "g1", "working_path": str(graph_work), "output_routes": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(runtime_root))

    agent = SimpleNamespace(_agentpark_graph_id="g1", config={"working_path": str(node_work)})

    assert module.resolve_agent_relative_path("src/app.py", agent=agent) == str(node_work / "src" / "app.py")
