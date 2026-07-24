from __future__ import annotations

import json
from pathlib import Path


def test_ue_crash_analyzer_profile_matches_gpt_newest_shared_runtime_configuration():
    workspace_root = Path(__file__).resolve().parents[1]
    gpt_newest = json.loads((workspace_root / "agent" / "GPT_Newest.json").read_text(encoding="utf-8"))
    analyzer = json.loads((workspace_root / "agent" / "UECrashAnalyzer.json").read_text(encoding="utf-8"))

    assert analyzer["id"] == "UECrashAnalyzer"
    assert analyzer["node_type_id"] == gpt_newest["node_type_id"]
    assert analyzer["source_graph_id"] == gpt_newest["source_graph_id"]
    assert analyzer["source_node_id"] == gpt_newest["source_node_id"]

    runtime_fields = (
        "skills",
        "provider_id",
        "instruction",
        "mode",
        "collaboration_mode",
        "tools",
        "mcp_servers",
        "web_search",
        "thinking",
        "reasoning_effort",
    )
    for field in runtime_fields:
        assert analyzer["fields"][field] == gpt_newest["fields"][field]
    assert isinstance(analyzer["fields"]["working_path"], str)
    assert analyzer["fields"]["plugins"] == ["unreal-engine"]


def test_ue_crash_analyzer_profile_requires_node_local_report():
    workspace_root = Path(__file__).resolve().parents[1]
    analyzer = json.loads((workspace_root / "agent" / "UECrashAnalyzer.json").read_text(encoding="utf-8"))
    system_prompt = analyzer["fields"]["system_prompt"]

    assert "当前工作目录就是节点自身路径" in system_prompt
    assert "UE崩溃分析报告.md" in system_prompt
    assert "不得修改、移动或删除原始崩溃资料" in system_prompt
