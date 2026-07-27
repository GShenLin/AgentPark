from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from functions.apply_patch_tool import apply_patch_declaration
from src.providers.openai_responses_runtime import OpenAIResponsesRuntime
from src.tool.workspace_exec_tools import workspace_exec_declaration


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_gpt1_keeps_the_single_system_tool_r30_profile():
    profile = json.loads((PROJECT_ROOT / "agent" / "GPT1.json").read_text(encoding="utf-8"))

    assert profile["fields"]["provider_id"] == "GPT_Official"
    assert profile["fields"]["tools"] == ["system_tools"]
    assert profile["fields"]["plugins"] == []
    assert profile["fields"]["skills"] == ["ark-doc-cli"]
    assert profile["fields"]["mcp_servers"] == ["ark-docs-mcp"]


def test_r30_tool_wire_contract_has_no_post_r30_lifecycle_fields():
    direct_patch = apply_patch_declaration["function"]["parameters"]
    workspace = workspace_exec_declaration["function"]["parameters"]

    assert direct_patch["required"] == ["patch"]
    assert "required_changes" not in direct_patch["properties"]
    assert workspace["required"] == ["stages"]
    assert set(workspace["properties"]) == {"stages"}


def test_gpt_official_uses_r30_request_contract():
    providers = json.loads(
        (PROJECT_ROOT / "config" / "modelProvider.json").read_text(encoding="utf-8")
    )["providers"]
    config = providers["GPT_Official"]
    runtime = SimpleNamespace(config=config)
    payload = OpenAIResponsesRuntime._responses_payload_extra(runtime, reasoning_effort="")

    assert config["responsesApi"] is True
    assert "responsesCompletedToolCheckpointEnabled" not in config
    assert "prompt_cache_key" not in payload
