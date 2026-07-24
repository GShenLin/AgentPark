from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

import functions.system_tools as system_tools
from src.runtime_cancellation import current_tool_call_cancel_source
from src.runtime_cancellation import tool_call_cancellation_scope
from src.tool.base_tool import BaseTool
from src.tool.workspace_exec_tools import workspace_exec
from src.workspace_execution import WorkspaceExecutionContractError


class _DummyAgent:
    config = {}


class _BudgetAgent:
    def __init__(self, memory_path: Path, *, limit: int):
        self.current_memory_path = str(memory_path)
        self.config = {"toolResultSubmissionMaxChars": limit}


def test_system_tools_exposes_workspace_exec_instead_of_parallel_wrapper():
    tools = BaseTool(_DummyAgent())
    tools.addTool("system_tools")

    assert "workspace_exec" in tools.function_map
    assert "multi_tool_use_parallel" not in tools.function_map
    assert "workspace_exec" in system_tools.__all__
    assert "multi_tool_use_parallel" not in system_tools.__all__


def test_builtin_code_agent_prompts_use_the_workspace_program_contract():
    root = Path(__file__).resolve().parents[1]
    for relative_path in ("agent/GPT.json", "agent/XYJProgrammer.json"):
        payload = json.loads((root / relative_path).read_text(encoding="utf-8"))
        prompt = payload["fields"]["system_prompt"]
        assert "workspace_exec" in prompt
        assert "multi_tool_use_parallel" not in prompt


def test_core_dev_plugin_uses_the_new_primary_code_tool_boundary():
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "plugins/core-dev/agentpark.plugin.json").read_text(encoding="utf-8")
    )

    assert payload["tools"] == ["system_tools"]


def test_parallel_execution_tool_does_not_claim_subagent_capability():
    from src.web_backend.companion_capabilities import infer_node_can

    assert infer_node_can({"tools": ["system_tools"]})["spawn_sub_agents"] is False


def test_workspace_exec_declaration_has_kind_specific_strict_arguments():
    from src.tool.workspace_exec_tools import workspace_exec_declaration

    description = workspace_exec_declaration["function"]["description"]
    stage_schema = workspace_exec_declaration["function"]["parameters"]["properties"]["stages"]["items"]
    stage_variants = stage_schema["oneOf"]
    variants = []
    for stage_variant in stage_variants:
        operation_items = stage_variant["properties"]["operations"]["items"]
        variants.extend(operation_items.get("oneOf", [operation_items]))

    assert "retain_until_next_handoff" in description
    assert "retire_after_verified" in description
    checkpoint_schema = workspace_exec_declaration["function"]["parameters"]["properties"][
        "context_checkpoint"
    ]
    assert set(checkpoint_schema["enum"]) == {
        "none",
        "retain_until_next_handoff",
        "retire_after_verified",
    }
    assert {item["properties"]["kind"]["enum"][0] for item in variants} == {
        "read_file",
        "search_text",
        "list_files",
        "run_command",
        "apply_patch",
        "update_task_direction",
    }
    assert all(item["properties"]["arguments"]["additionalProperties"] is False for item in variants)
    mutation_stages = stage_variants[1:]
    assert all(stage["properties"]["operations"]["maxItems"] == 1 for stage in mutation_stages)
    patch_arguments = {
        item["properties"]["kind"]["enum"][0]: item["properties"]["arguments"]
        for item in variants
    }["apply_patch"]
    assert "required_changes" in patch_arguments["required"]
    assert patch_arguments["properties"]["required_changes"]["minItems"] == 1


def test_workspace_exec_runs_operations_in_a_stage_concurrently(monkeypatch):
    import src.workspace_execution as execution

    def delayed_read(file_path, **_kwargs):
        time.sleep(0.15)
        return json.dumps({"status": "success", "file_path": file_path})

    monkeypatch.setattr(execution, "read_file", delayed_read)
    started = time.monotonic()
    result = json.loads(
        workspace_exec(
            [
                {
                    "id": "inspect",
                    "operations": [
                        {"id": "a", "kind": "read_file", "arguments": {"file_path": "a.py"}},
                        {"id": "b", "kind": "read_file", "arguments": {"file_path": "b.py"}},
                    ],
                }
            ],
            agent=_DummyAgent(),
        )
    )

    assert time.monotonic() - started < 0.27
    assert result["status"] == "success"
    assert [item["id"] for item in result["stages"][0]["operations"]] == ["a", "b"]


def test_workspace_exec_propagates_tool_call_cancellation_context_to_workers(monkeypatch):
    import threading
    import src.workspace_execution as execution

    cancel_event = threading.Event()
    observed = []

    def read(file_path, **_kwargs):
        observed.append((file_path, current_tool_call_cancel_source()))
        return json.dumps({"status": "success", "file_path": file_path})

    monkeypatch.setattr(execution, "read_file", read)
    with tool_call_cancellation_scope(cancel_event):
        result = json.loads(
            workspace_exec(
                [
                    {
                        "id": "inspect",
                        "operations": [
                            {"id": "a", "kind": "read_file", "arguments": {"file_path": "a.py"}},
                            {"id": "b", "kind": "read_file", "arguments": {"file_path": "b.py"}},
                        ],
                    }
                ],
                agent=_DummyAgent(),
            )
        )

    assert result["status"] == "success"
    assert observed == [("a.py", cancel_event), ("b.py", cancel_event)]


def test_workspace_exec_runs_stages_sequentially(monkeypatch):
    import src.workspace_execution as execution

    observed: list[str] = []

    def read(file_path, **_kwargs):
        observed.append(file_path)
        return json.dumps({"status": "success", "file_path": file_path})

    monkeypatch.setattr(execution, "read_file", read)
    result = json.loads(
        workspace_exec(
            [
                {
                    "id": "first",
                    "operations": [
                        {"id": "a", "kind": "read_file", "arguments": {"file_path": "a.py"}}
                    ],
                },
                {
                    "id": "second",
                    "operations": [
                        {"id": "b", "kind": "read_file", "arguments": {"file_path": "b.py"}}
                    ],
                },
            ],
            agent=_DummyAgent(),
        )
    )

    assert result["status"] == "success"
    assert observed == ["a.py", "b.py"]


def test_workspace_exec_resolves_prior_stage_result_references(monkeypatch):
    import src.workspace_execution as execution

    monkeypatch.setattr(
        execution,
        "rg_list_files",
        lambda **_kwargs: json.dumps(
            {"status": "success", "files": [{"file_path": "selected.py"}]}
        ),
    )
    observed: list[str] = []

    def read(file_path, **_kwargs):
        observed.append(file_path)
        return json.dumps({"status": "success", "file_path": file_path})

    monkeypatch.setattr(execution, "read_file", read)
    result = json.loads(
        workspace_exec(
            [
                {
                    "id": "discover",
                    "operations": [
                        {"id": "files", "kind": "list_files", "arguments": {}}
                    ],
                },
                {
                    "id": "inspect",
                    "operations": [
                        {
                            "id": "read_selected",
                            "kind": "read_file",
                            "arguments": {
                                "file_path": {
                                    "$ref": "files",
                                    "path": ["result", "files", 0, "file_path"],
                                }
                            },
                        }
                    ],
                },
            ],
            agent=_DummyAgent(),
        )
    )

    assert result["status"] == "success"
    assert observed == ["selected.py"]


@pytest.mark.parametrize(
    "stages, error",
    [
        ([], "non-empty"),
        (
            [{"id": "s", "operations": [{"id": "x", "kind": "unknown", "arguments": {}}]}],
            "must be one of",
        ),
        (
            [
                {
                    "id": "s",
                    "operations": [
                        {
                            "id": "x",
                            "kind": "read_file",
                            "arguments": {"file_path": "a.py", "unexpected": True},
                        }
                    ],
                }
            ],
            "unknown fields",
        ),
        (
            [
                {
                    "id": "s",
                    "operations": [
                        {"id": "x", "kind": "read_file", "arguments": {"file_path": "a.py"}},
                        {"id": "x", "kind": "read_file", "arguments": {"file_path": "b.py"}},
                    ],
                }
            ],
            "duplicate operation id",
        ),
        (
            [
                {
                    "id": "s",
                    "operations": [
                        {
                            "id": "x",
                            "kind": "read_file",
                            "arguments": {
                                "file_path": {"$ref": "x", "path": ["result", "file_path"]}
                            },
                        }
                    ],
                }
            ],
            "before it has completed",
        ),
    ],
)
def test_workspace_exec_rejects_contract_violations(stages, error):
    with pytest.raises(WorkspaceExecutionContractError, match=error):
        workspace_exec(stages, agent=_DummyAgent())


def test_workspace_exec_preserves_individual_operation_failure(monkeypatch):
    import src.workspace_execution as execution

    monkeypatch.setattr(
        execution,
        "read_file",
        lambda **_kwargs: json.dumps({"status": "error", "error": "missing"}),
    )
    result = json.loads(
        workspace_exec(
            [
                {
                    "id": "inspect",
                    "operations": [
                        {"id": "missing", "kind": "read_file", "arguments": {"file_path": "x.py"}}
                    ],
                }
            ],
            agent=_DummyAgent(),
        )
    )

    assert result["status"] == "error"
    operation = result["stages"][0]["operations"][0]
    assert operation["status"] == "error"
    assert operation["result"]["error"] == "missing"


def test_workspace_exec_compacts_to_provider_limit_with_attributable_previews(
    monkeypatch,
    tmp_path,
):
    import src.workspace_execution as execution

    def large_read(file_path, **_kwargs):
        return json.dumps(
            {
                "status": "success",
                "file_path": file_path,
                "content": f"HEAD:{file_path}\n" + ("x" * 30_000) + f"\nTAIL:{file_path}",
            }
        )

    monkeypatch.setattr(execution, "read_file", large_read)
    agent = _BudgetAgent(tmp_path / "node" / "memory.md", limit=5000)
    serialized = workspace_exec(
        [
            {
                "id": "inspect",
                "operations": [
                    {
                        "id": "first",
                        "kind": "read_file",
                        "arguments": {"file_path": "first.py"},
                    },
                    {
                        "id": "second",
                        "kind": "read_file",
                        "arguments": {"file_path": "second.py"},
                    },
                ],
            }
        ],
        agent=agent,
    )
    result = json.loads(serialized)

    assert len(serialized) <= 5000
    assert result["status"] == "success"
    assert result["result_compacted"] is True
    assert Path(result["artifact_path"]).is_file()
    operations = result["stages"][0]["operations"]
    assert [item["id"] for item in operations] == ["first", "second"]
    assert all(item["result"]["compacted"] is True for item in operations)
    assert "HEAD:first.py" in operations[0]["result"]["preview"]
    assert "TAIL:first.py" in operations[0]["result"]["preview"]

    artifact = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    full_result = json.loads(artifact["content"])
    assert full_result["stages"][0]["operations"][1]["result"]["content"].endswith(
        "TAIL:second.py"
    )


def test_workspace_exec_rejects_invalid_provider_submission_limit(monkeypatch):
    import src.workspace_execution as execution

    monkeypatch.setattr(
        execution,
        "read_file",
        lambda **_kwargs: json.dumps({"status": "success", "content": "ok"}),
    )
    agent = _DummyAgent()
    agent.config = {"toolResultSubmissionMaxChars": "5000"}
    try:
        with pytest.raises(
            WorkspaceExecutionContractError,
            match="toolResultSubmissionMaxChars must be a positive integer",
        ):
            workspace_exec(
                [
                    {
                        "id": "inspect",
                        "operations": [
                            {
                                "id": "read",
                                "kind": "read_file",
                                "arguments": {"file_path": "file.py"},
                            }
                        ],
                    }
                ],
                agent=agent,
            )
    finally:
        agent.config = {}
