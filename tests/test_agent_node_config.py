import json


def test_agent_node_run_request_prefers_config_file_over_context(tmp_path):
    from nodes.agent_node_config import load_agent_node_run_request

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider_id": "from-file",
                "instruction": "from instruction file field",
                "system_prompt": "from system prompt field",
                "collaboration_mode": "plan",
                "working_path": "C:/Project",
            }
        ),
        encoding="utf-8",
    )

    request = load_agent_node_run_request(
        {
            "node_instance_id": "Agent1",
            "graph_id": "g1",
            "provider_id": "from-context",
        },
        config_path=str(config_path),
    )

    assert request.agent_id == "Agent1"
    assert request.graph_id == "g1"
    assert request.provider_id == "from-file"
    assert request.instruction == "from instruction file field"
    assert request.system_prompt == "from system prompt field"
    assert not hasattr(request, "mode")
    assert request.collaboration_mode == "plan"
    assert request.working_path == "C:/Project"
    assert request.setting("provider_id") == "from-file"


def test_agent_node_run_request_requires_provider_id(tmp_path):
    import pytest
    from nodes.agent_node_config import AgentNodeConfigError
    from nodes.agent_node_config import load_agent_node_run_request

    with pytest.raises(AgentNodeConfigError, match="provider_id is required"):
        load_agent_node_run_request({"node_instance_id": "Agent1"}, config_path=str(tmp_path / "missing.json"))


def test_support_mode_is_resolved_from_provider_and_input_not_node_config():
    import pytest

    from nodes.agent_node_modes import resolve_input_support_mode

    assert resolve_input_support_mode(["audio_generation"], {"parts": []}) == "audio_generation"
    assert resolve_input_support_mode(["imagechat", "chat"], {"parts": []}) == "imagechat"
    assert resolve_input_support_mode(
        ["chat", "image_generation"],
        {"parts": [{"type": "meta", "meta": {"support_mode": "image_generation"}}]},
    ) == "image_generation"

    with pytest.raises(ValueError, match="does not declare requested SupportMode"):
        resolve_input_support_mode(
            ["chat"],
            {"parts": [{"type": "meta", "meta": {"support_mode": "audio_generation"}}]},
        )
