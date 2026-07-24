import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.web_backend.settings_api import SettingsApiDomain


def test_settings_api_reads_and_writes_model_provider(monkeypatch, tmp_path):
    from src import workspace_settings

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    provider_path = config_dir / "modelProvider.json"
    provider_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "openai",
                        "apiKey": "test-key",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("AGENTPARK_CONFIG_PATH", raising=False)
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    domain = SettingsApiDomain(SimpleNamespace())

    loaded = domain.get_settings_section("model-provider")
    assert loaded["path"] == str(provider_path)
    assert loaded["data"]["providers"]["demo"]["type"] == "openai"

    result = domain.update_settings_section(
        "model-provider",
        {
            "content": json.dumps(
                {
                    "providers": {
                        "demo": {
                            "type": "gemini",
                            "apiKey": "test-key",
                        }
                    }
                },
                ensure_ascii=False,
            )
        },
    )

    assert result["ok"] is True
    saved = json.loads(provider_path.read_text(encoding="utf-8"))
    assert saved["providers"]["demo"]["type"] == "gemini"


def test_settings_api_rejects_model_provider_without_providers(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.delenv("AGENTPARK_CONFIG_PATH", raising=False)
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    domain = SettingsApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.update_settings_section("model-provider", {"content": "{}"})

    assert exc.value.status_code == 400
    assert "providers" in str(exc.value.detail)


def test_settings_api_rejects_invalid_responses_provider_contract(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.delenv("AGENTPARK_CONFIG_PATH", raising=False)
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    domain = SettingsApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.update_settings_section(
            "model-provider",
            {
                "content": json.dumps(
                    {
                        "providers": {
                            "fable-5-krill": {
                                "type": "openai",
                                "apiKey": "test-key",
                                "responsesApi": True,
                                "toolResultSubmissionMaxChars": 50000,
                            }
                        }
                    }
                )
            },
        )

    assert exc.value.status_code == 400
    assert "fable-5-krill" in str(exc.value.detail)
    assert "toolContextCompactionEnabled" in str(exc.value.detail)


def test_settings_api_reads_invalid_provider_contract_with_warning(monkeypatch, tmp_path):
    from src import workspace_settings

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    provider_path = config_dir / "modelProvider.json"
    provider_path.write_text(
        json.dumps(
            {
                "providers": {
                    "bad": {"type": "grok", "authMode": "codex", "responsesApi": True}
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("AGENTPARK_CONFIG_PATH", raising=False)
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    loaded = SettingsApiDomain(SimpleNamespace()).get_settings_section("model-provider")

    assert loaded["data"]["providers"]["bad"]["type"] == "grok"
    assert loaded["warnings"] == [
        "Provider 'bad' can use authMode 'codex' only with type 'openai'."
    ]


def test_settings_api_rejects_invalid_defaults_section(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    domain = SettingsApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.update_settings_section("defaults", {"content": json.dumps({"server": "127.0.0.1"})})

    assert exc.value.status_code == 400
    assert "server" in str(exc.value.detail)


def test_settings_api_marks_changed_memories_path_as_restart_required(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.web_backend import runtime_paths

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    active_root = tmp_path / "memories"
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(active_root))
    domain = SettingsApiDomain(SimpleNamespace())
    configured_root = tmp_path / "data" / "memories"

    result = domain.update_settings_section(
        "defaults",
        {"content": json.dumps({"storage": {"memoriesPath": str(configured_root)}})},
    )

    assert result["restart_required"] is True
    assert result["runtime"] == {
        "active_memories_root": str(active_root),
        "configured_memories_root": str(configured_root),
    }
    assert json.loads((tmp_path / ".cache" / "memoryLocalConfig.json").read_text(encoding="utf-8")) == {
        "memoriesPath": str(configured_root),
    }
    assert "storage" not in json.loads((config_dir / "config.json").read_text(encoding="utf-8"))


def test_settings_api_merges_memory_local_config_into_defaults(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.web_backend import runtime_paths

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "server": {"port": 9001},
                "storage": {"memoriesPath": str(tmp_path / "legacy-memories")},
            }
        ),
        encoding="utf-8",
    )
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    configured_root = tmp_path / "external-memories"
    (cache_dir / "memoryLocalConfig.json").write_text(
        json.dumps({"memoriesPath": str(configured_root)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))

    result = SettingsApiDomain(SimpleNamespace()).get_settings_section("defaults")

    assert result["data"]["server"] == {"port": 9001}
    assert result["data"]["storage"] == {"memoriesPath": str(configured_root)}
    assert json.loads(result["content"])["storage"] == {"memoriesPath": str(configured_root)}


def test_settings_api_falls_back_for_relative_memories_path(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.web_backend import runtime_paths

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    domain = SettingsApiDomain(SimpleNamespace())

    result = domain.update_settings_section(
        "defaults",
        {"content": json.dumps({"storage": {"memoriesPath": "data/memories"}})},
    )

    assert result["restart_required"] is False
    assert result["runtime"]["configured_memories_root"] == str(tmp_path / "memories")


def test_settings_api_rejects_invalid_undo_max_steps(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    domain = SettingsApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.update_settings_section(
            "defaults",
            {"content": json.dumps({"undo": {"maxSteps": 101}})},
        )

    assert exc.value.status_code == 400
    assert "undo.maxSteps" in str(exc.value.detail)


def test_settings_api_rejects_non_boolean_companion_node_review_switch(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    domain = SettingsApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.update_settings_section(
            "defaults",
            {"content": json.dumps({"agentNode": {"reviewNodeRunsWithCompanion": "yes"}})},
        )

    assert exc.value.status_code == 400
    assert "reviewNodeRunsWithCompanion" in str(exc.value.detail)


def test_settings_api_rejects_non_boolean_tool_failure_memory_switch(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    domain = SettingsApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.update_settings_section(
            "defaults",
            {"content": json.dumps({"agentNode": {"reviseToolFailureMemoryWithCompanion": "yes"}})},
        )

    assert exc.value.status_code == 400
    assert "reviseToolFailureMemoryWithCompanion" in str(exc.value.detail)


def test_settings_api_reads_and_writes_companion_config(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    companion_dir = graphs_dir / "Companion" / "Companion"
    companion_dir.mkdir(parents=True)
    companion_path = companion_dir / "config.json"
    companion_path.write_text(
        json.dumps(
            {
                "node_id": "Companion",
                "type_id": "agent_node",
                "graph_id": "Companion",
                "provider_id": "demo",
                "tools": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))

    domain = SettingsApiDomain(SimpleNamespace())

    loaded = domain.get_settings_section("companion")
    assert loaded["path"] == str(companion_path)
    assert loaded["data"]["provider_id"] == "demo"

    result = domain.update_settings_section(
        "companion",
        {
            "content": json.dumps(
                {
                    "node_id": "Companion",
                    "type_id": "agent_node",
                    "graph_id": "Companion",
                    "provider_id": "next",
                    "tools": ["file_read_tools"],
                },
                ensure_ascii=False,
            )
        },
    )

    assert result["ok"] is True
    saved = json.loads(companion_path.read_text(encoding="utf-8"))
    assert saved["provider_id"] == "next"
    assert saved["tools"] == ["file_read_tools"]


def test_settings_api_rejects_invalid_companion_config(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path))

    domain = SettingsApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.update_settings_section("companion", {"content": json.dumps({"type_id": "echo_node"})})

    assert exc.value.status_code == 400
    assert "agent_node" in str(exc.value.detail)


def test_settings_api_exposes_events_config_and_validates_updates(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    calls = []

    class Registry:
        def compile(self, payload, *, strict_sources):
            calls.append((payload, strict_sources))

    domain = SettingsApiDomain(SimpleNamespace(runtime_events=SimpleNamespace(registry=Registry())))

    loaded = domain.get_settings_section("events")

    assert loaded["path"] == str(tmp_path / "config" / "events.json")
    assert loaded["data"]["schema_version"] == 1
    assert (tmp_path / "config" / "events.json").exists()

    payload = dict(loaded["data"])
    payload["enabled"] = False
    result = domain.update_settings_section("events", {"content": json.dumps(payload)})

    assert result["ok"] is True
    assert result["data"]["enabled"] is False
    assert calls[-1][1] is True
    saved = json.loads((tmp_path / "config" / "events.json").read_text(encoding="utf-8"))
    assert saved["enabled"] is False


def test_settings_api_reads_tool_stats(monkeypatch, tmp_path):
    from src.tool import tool_stats_store

    monkeypatch.setattr(tool_stats_store, "get_workspace_cache_dir", lambda: str(tmp_path / ".cache"))
    recorder = tool_stats_store.ToolCallStatsRecorder(provider_id="demo")
    recorder.handle(
        {
            "type": "tool_call_start",
            "name": "read_file",
            "call_id": "call-1",
            "arguments": {"path": "notes.txt"},
        }
    )
    recorder.handle(
        {
            "type": "tool_call_end",
            "name": "read_file",
            "call_id": "call-1",
            "status": "failed",
            "error": "file not found",
            "result": {"status": "failed", "error": "file not found"},
            "result_preview": '{"status":"failed","error":"file not found"}',
            "diagnostics": ["resolved path does not exist"],
        }
    )

    domain = SettingsApiDomain(SimpleNamespace())
    result = domain.get_tool_stats()

    assert result["summary"]["providers"]["demo"]["total"] == 1
    assert result["recent_calls"][0]["tool_name"] == "read_file"
    assert result["recent_calls"][0]["tool_call_arguments"] == {"path": "notes.txt"}
    assert result["recent_calls"][0]["error"] == "file not found"
    assert result["recent_calls"][0]["result"] == {"status": "failed", "error": "file not found"}
    assert result["recent_calls"][0]["diagnostics"] == ["resolved path does not exist"]
    assert result["failure_analysis"]["total_failures"] == 1
    assert result["failure_analysis"]["categories"][0]["category"] == "read_failed"


def test_settings_api_reads_complete_failure_history_for_tool(monkeypatch, tmp_path):
    from src.tool import tool_stats_store

    monkeypatch.setattr(tool_stats_store, "get_workspace_cache_dir", lambda: str(tmp_path / ".cache"))
    recorder = tool_stats_store.ToolCallStatsRecorder(provider_id="demo")
    for call_id, status in (("call-1", "failed"), ("call-2", "completed"), ("call-3", "timeout")):
        recorder.handle(
            {
                "type": "tool_call_start",
                "name": "read_file",
                "call_id": call_id,
                "arguments": {"file_path": f"{call_id}.txt"},
            }
        )
        recorder.handle(
            {
                "type": "tool_call_end",
                "name": "read_file",
                "call_id": call_id,
                "status": status,
                "error": "read failed" if status != "completed" else "",
            }
        )

    result = SettingsApiDomain(SimpleNamespace()).get_tool_failure_history("read_file")

    assert result["tool_name"] == "read_file"
    assert result["failure_count"] == 2
    assert [call["call_id"] for call in result["calls"]] == ["call-3", "call-1"]
    assert result["calls"][0]["tool_call_arguments"] == {"file_path": "call-3.txt"}


def test_settings_api_clears_tool_stats(monkeypatch, tmp_path):
    from src.tool import tool_stats_store

    monkeypatch.setattr(tool_stats_store, "get_workspace_cache_dir", lambda: str(tmp_path / ".cache"))
    recorder = tool_stats_store.ToolCallStatsRecorder(provider_id="demo")
    recorder.handle({"type": "tool_call_start", "name": "read_file", "call_id": "call-1"})
    recorder.handle({"type": "tool_call_end", "name": "read_file", "call_id": "call-1", "status": "completed"})

    domain = SettingsApiDomain(SimpleNamespace())
    result = domain.clear_tool_stats()

    assert result["ok"] is True
    assert result["summary"] == {"providers": {}}
    assert result["recent_calls"] == []
    assert result["failure_analysis"]["total_failures"] == 0


def test_settings_api_delete_optional_memory_runs_bat(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.web_backend import runtime_paths, settings_maintenance

    script_path = tmp_path / "delete_operational_memory.bat"
    script_path.write_text("@echo off\necho Deleted 2 files. Failed 0 files. Matched 2 files.\n", encoding="utf-8")
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout="Deleted 2 files. Failed 0 files. Matched 2 files.\n",
            stderr="",
        )

    monkeypatch.setattr(settings_maintenance.subprocess, "run", fake_run)

    domain = SettingsApiDomain(SimpleNamespace())
    result = domain.delete_optional_memory()

    assert result["ok"] is True
    assert result["stdout"] == "Deleted 2 files. Failed 0 files. Matched 2 files."
    assert calls
    assert calls[0][1]["cwd"] == str(tmp_path)
    assert str(script_path) in calls[0][0]
    assert str(tmp_path / "memories") in calls[0][0]


def test_settings_api_clear_logs_runs_clear_log_bat(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.web_backend import runtime_paths, settings_maintenance

    script_path = tmp_path / "ClearLog.bat"
    script_path.write_text("@echo off\necho Cleared 4 log files. Failed 0 files. Matched 4 files.\n", encoding="utf-8")
    memories_root = tmp_path / "external-memories"
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(memories_root))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout="Cleared 4 log files. Failed 0 files. Matched 4 files.\n",
            stderr="",
        )

    monkeypatch.setattr(settings_maintenance.subprocess, "run", fake_run)

    result = SettingsApiDomain(SimpleNamespace()).clear_logs()

    assert result["ok"] is True
    assert result["stdout"].startswith("Cleared 4 log files")
    assert str(script_path) in calls[0][0]
    assert str(memories_root) in calls[0][0]


def test_settings_api_starts_automatic_provider_channel_tests():
    calls = []

    class Jobs:
        def latest_running(self):
            return None

        def start(self, *, timeout_seconds):
            calls.append(timeout_seconds)
            return {"job_id": "job-1", "status": "running"}

        def read_result(self):
            return {"providers": {}, "path": "ProviderLimit.json"}

    domain = SettingsApiDomain(SimpleNamespace(provider_limit_jobs=Jobs()))
    result = domain.start_provider_limit_tests({"timeout_seconds": 12})

    assert result["job"]["status"] == "running"
    assert calls == [12.0]
