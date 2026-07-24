from pathlib import Path

from nodes.agent_tool_loader import list_available_tool_options
from src.tool.base_tool import BaseTool


class DummyAgent:
    config = {}


def _function_names(tool: BaseTool) -> set[str]:
    return {
        item.get("function", {}).get("name")
        for item in tool.tool_declarations
        if isinstance(item, dict)
    }


def test_code_read_tools_exposes_only_read_investigation_tools():
    tool = BaseTool(DummyAgent())
    tool.addTool("code_read_tools")

    assert _function_names(tool) == {"read_file", "rg_search_text", "rg_list_files"}
    assert "write_file" not in tool.function_map
    assert "apply_patch" not in tool.function_map
    assert "execute_console_command" not in tool.function_map
    assert "execute_curl_command" not in tool.function_map


def test_tool_bundle_split_exposes_expected_tools_only():
    expected = {
        "code_edit_tools": {"apply_patch", "write_file"},
        "shell_tools": {"execute_console_command"},
        "network_tools": {"execute_curl_command"},
    }

    for bundle_name, function_names in expected.items():
        tool = BaseTool(DummyAgent())
        tool.addTool(bundle_name)
        assert _function_names(tool) == function_names


def test_system_tools_excludes_curl():
    tool = BaseTool(DummyAgent())
    tool.addTool("system_tools")

    assert _function_names(tool) == {
        "apply_patch",
        "execute_console_command",
        "read_file",
        "rg_search_text",
        "rg_list_files",
        "workspace_exec",
        "get_task_direction",
        "replace_task_direction",
        "update_task_direction",
        "run_analysis_verification",
        "finalize_analysis_report",
    }
    assert "write_file" not in tool.function_map
    assert "execute_curl_command" not in tool.function_map


def test_mandatory_system_tool_modules_are_not_user_configurable():
    root = Path(__file__).resolve().parents[1]
    available = {
        item["value"]
        for item in list_available_tool_options(str(root / "functions"))
    }

    assert {
        "analysis_report_tools",
        "analysis_verification_tools",
        "cancer_control",
        "task_direction_tools",
        "ue_remote_control",
        "workspace_exec_tools",
    }.isdisjoint(available)
