from __future__ import annotations

import json

from src.companion_cli_window import CompanionCliWindowStatus


def _write_companion_config(tmp_path) -> None:
    config_path = tmp_path / "memories" / "Companion" / "Companion" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "graph_id": "Companion",
                "node_id": "Companion",
                "type_id": "agent_node",
                "working_path": "",
            }
        ),
        encoding="utf-8",
    )


def test_hidden_cli_is_shown_and_working_path_is_updated(monkeypatch, tmp_path):
    import src.ask_here_companion as companion
    from src.web_backend import runtime_paths

    _write_companion_config(tmp_path)
    target = tmp_path / "project"
    target.mkdir()
    shown = []
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    monkeypatch.setattr(
        companion,
        "get_companion_cli_window_status",
        lambda: CompanionCliWindowStatus(running=True, visible=False, pid=42, handle=99),
    )
    monkeypatch.setattr(companion, "show_companion_cli_window", lambda: shown.append(True))
    monkeypatch.setattr(
        companion,
        "launch_agentpark_hidden",
        lambda: (_ for _ in ()).throw(AssertionError("running CLI must not be relaunched")),
    )

    result = companion.dispatch_to_companion_cli(str(target))

    assert result["mode"] == "companion_cli_shown"
    assert shown == [True]
    stored = json.loads(
        (tmp_path / "memories" / "Companion" / "Companion" / "config.json").read_text(encoding="utf-8")
    )
    assert stored["working_path"] == str(target)


def test_visible_cli_only_updates_working_path(monkeypatch, tmp_path):
    import src.ask_here_companion as companion
    from src.web_backend import runtime_paths

    _write_companion_config(tmp_path)
    target = tmp_path / "project"
    target.mkdir()
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    monkeypatch.setattr(
        companion,
        "get_companion_cli_window_status",
        lambda: CompanionCliWindowStatus(running=True, visible=True, pid=42, handle=99),
    )
    monkeypatch.setattr(
        companion,
        "show_companion_cli_window",
        lambda: (_ for _ in ()).throw(AssertionError("visible CLI must not be toggled")),
    )

    result = companion.dispatch_to_companion_cli(str(target))

    assert result["mode"] == "companion_cli_path_updated"


def test_missing_cli_starts_project_waits_and_shows_window(monkeypatch, tmp_path):
    import src.ask_here_companion as companion
    from src.web_backend import runtime_paths

    _write_companion_config(tmp_path)
    target = tmp_path / "project"
    target.mkdir()
    shown = []
    statuses = iter(
        [
            CompanionCliWindowStatus(running=False, visible=False),
            CompanionCliWindowStatus(running=True, visible=False, pid=84, handle=101),
        ]
    )
    monkeypatch.delenv("AGENTPARK_ASK_HERE_PROJECT_STARTING", raising=False)
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    monkeypatch.setattr(companion, "get_companion_cli_window_status", lambda: next(statuses))
    monkeypatch.setattr(companion, "launch_agentpark_hidden", lambda: 500)
    monkeypatch.setattr(companion, "show_companion_cli_window", lambda: shown.append(True))

    result = companion.dispatch_to_companion_cli(str(target))

    assert result == {
        "mode": "companion_cli_started",
        "working_path": str(target),
        "pid": 84,
        "launcher_pid": 500,
    }
    assert shown == [True]
