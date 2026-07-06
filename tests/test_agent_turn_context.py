from types import SimpleNamespace


def test_agent_turn_context_item_excludes_secrets_and_splits_volatile_fields(tmp_path):
    from src.providers.agent_turn_context import build_agent_turn_context_item

    agent = SimpleNamespace(
        provider_name="krill_gpt55",
        _agentpark_node_type_id="agent_node",
        _agentpark_working_path=str(tmp_path),
        config={
            "apiKey": "sk-secret",
            "baseUrl": "https://example.invalid/v1",
            "type": "openai",
            "model": "gpt-test",
            "responsesApi": True,
            "responsesContinuationMode": "explicit_context",
            "reasoningEffort": "high",
        },
    )

    item = build_agent_turn_context_item(
        agent,
        environment_context={
            "workspace_path": str(tmp_path),
            "shell": "powershell",
            "request_time": "2026-07-02T10:00:00+08:00",
        },
        tools_payload=[
            {"type": "function", "name": "read_file", "parameters": {"type": "object"}},
            {"type": "function", "name": "read_file", "parameters": {"type": "object"}},
            {"type": "web_search"},
        ],
        responses_mode="item_level",
        requested_responses_mode="responses_api",
    )

    text = str(item)
    assert "sk-secret" not in text
    assert "example.invalid" not in text
    assert item["environment"] == {"workspace_path": str(tmp_path), "shell": "powershell"}
    assert item["permissions"] == {
        "sandbox_mode": "danger-full-access",
        "network_access": "enabled",
        "approval_policy": "never",
    }
    assert item["collaboration_mode"] == {"mode": "default"}
    assert item["volatile"] == {"request_time": "2026-07-02T10:00:00+08:00"}
    assert item["tools"] == {"names": ["read_file", "web_search"], "count": 2}


def test_agent_turn_context_project_instructions_uses_text_hash(tmp_path):
    from src.providers.agent_project_instructions import project_instructions_text_hash
    from src.providers.agent_turn_context import build_agent_turn_context_item
    from src.providers.agent_turn_context import build_agent_turn_context_update

    agent = SimpleNamespace(provider_name="openai", config={"type": "openai", "model": "gpt-test"})
    first = build_agent_turn_context_item(
        agent,
        project_instructions_context={
            "directory": str(tmp_path),
            "paths": [str(tmp_path / "AGENTS.md")],
            "text": "abc",
        },
    )
    second = build_agent_turn_context_item(
        agent,
        project_instructions_context={
            "directory": str(tmp_path),
            "paths": [str(tmp_path / "AGENTS.md")],
            "text": "xyz",
        },
    )

    assert first["project_instructions"]["text_hash"] == project_instructions_text_hash("abc")
    update = build_agent_turn_context_update(first, second, request_index=2)
    assert update["context_update_mode"] == "diff"
    assert "project_instructions.text_hash" in update["context_diff"]["changed_paths"]


def test_agent_turn_context_update_ignores_request_time_for_diff(tmp_path):
    from src.providers.agent_turn_context import build_agent_turn_context_item
    from src.providers.agent_turn_context import build_agent_turn_context_update
    from src.providers.agent_turn_context import format_agent_turn_context_update
    from src.providers.agent_turn_context import is_agent_turn_context_text

    agent = SimpleNamespace(provider_name="openai", config={"type": "openai", "model": "gpt-test"})
    first = build_agent_turn_context_item(
        agent,
        environment_context={
            "workspace_path": str(tmp_path),
            "shell": "powershell",
            "request_time": "2026-07-02T10:00:00+08:00",
        },
        tools_payload=[],
        responses_mode="item_level",
        requested_responses_mode="responses_api",
    )
    second = build_agent_turn_context_item(
        agent,
        environment_context={
            "workspace_path": str(tmp_path),
            "shell": "powershell",
            "request_time": "2026-07-02T10:00:01+08:00",
        },
        tools_payload=[],
        responses_mode="item_level",
        requested_responses_mode="responses_api",
    )

    full = build_agent_turn_context_update(None, first, request_index=1)
    unchanged = build_agent_turn_context_update(first, second, request_index=2)

    assert full["context_update_mode"] == "full"
    assert "volatile" not in full["context_item"]
    assert unchanged["context_update_mode"] == "unchanged"
    text = format_agent_turn_context_update(full)
    assert is_agent_turn_context_text(text)
    assert "2026-07-02T10:00:00+08:00" not in text


def test_agent_turn_context_diff_detects_collaboration_mode_change():
    from src.providers.agent_turn_context import build_agent_turn_context_item
    from src.providers.agent_turn_context import build_agent_turn_context_update

    first_agent = SimpleNamespace(provider_name="openai", config={"type": "openai", "model": "gpt-test"})
    second_agent = SimpleNamespace(
        provider_name="openai",
        config={"type": "openai", "model": "gpt-test"},
        _agentpark_collaboration_mode="plan",
    )

    first = build_agent_turn_context_item(first_agent, environment_context={}, tools_payload=[])
    second = build_agent_turn_context_item(second_agent, environment_context={}, tools_payload=[])
    update = build_agent_turn_context_update(first, second, request_index=2)

    assert update["context_update_mode"] == "diff"
    assert update["context_diff"]["changed_paths"] == ["collaboration_mode.mode"]
    assert update["context_diff"]["changes"][0]["previous"] == "default"
    assert update["context_diff"]["changes"][0]["current"] == "plan"


def test_agent_turn_context_reference_round_trips_stable_item(tmp_path):
    from types import SimpleNamespace

    from src.providers.agent_turn_context import load_agent_turn_context_reference
    from src.providers.agent_turn_context import save_agent_turn_context_reference

    agent = SimpleNamespace(memory=SimpleNamespace(current_memory_path=str(tmp_path / "memory.md")))
    item = {
        "kind": "agent_turn_context",
        "environment": {"workspace_path": str(tmp_path), "shell": "powershell"},
        "volatile": {"request_time": "2026-07-02T10:00:00+08:00"},
    }

    save_agent_turn_context_reference(agent, item)
    loaded = load_agent_turn_context_reference(agent)

    assert loaded == {
        "kind": "agent_turn_context",
        "environment": {"workspace_path": str(tmp_path), "shell": "powershell"},
    }
