import json
import re
import sys
import time
import types

import functions.multi_tool_use_tools as parallel_tools
from src.tool.base_tool import BaseTool
from src.tool.tool_load_errors import ToolLoadError


class _DummyAgent:
    def __init__(self):
        self.config = {}

    def _resolve_parallel_workers(self, task_count):
        return task_count

    def execute_tool(self, name, args):
        if name == "sleep_a":
            time.sleep(0.2)
            return json.dumps({"status": "success", "name": "a", "args": args}, ensure_ascii=False)
        if name == "sleep_b":
            time.sleep(0.2)
            return json.dumps({"status": "success", "name": "b", "args": args}, ensure_ascii=False)
        return json.dumps({"status": "error", "error": f"unknown tool: {name}"}, ensure_ascii=False)


def test_multi_tool_use_parallel_runs_tasks_concurrently():
    agent = _DummyAgent()
    start = time.monotonic()
    raw = parallel_tools.multi_tool_use_parallel(
        tool_uses=[
            {"recipient_name": "functions.sleep_a", "parameters": {"x": 1}},
            {"recipient_name": "functions.sleep_b", "parameters": {"x": 2}},
        ],
        agent=agent,
    )
    elapsed = time.monotonic() - start

    payload = json.loads(raw)
    assert payload["status"] == "success"
    assert payload["summary"]["requested"] == 2
    assert payload["summary"]["failed"] == 0
    assert elapsed < 0.38

    results = payload["results"]
    assert results[0]["recipient_name"] == "functions.sleep_a"
    assert results[1]["recipient_name"] == "functions.sleep_b"
    assert results[0]["status"] == "success"
    assert results[1]["status"] == "success"


def test_multi_tool_use_parallel_rejects_invalid_recipient_namespace():
    agent = _DummyAgent()
    raw = parallel_tools.multi_tool_use_parallel(
        tool_uses=[
            {"recipient_name": "web.search_query", "parameters": {"q": "x"}},
        ],
        agent=agent,
    )
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert "must start with 'functions.'" in payload["error"]


def test_multi_tool_use_parallel_rejects_slow_console_timeout():
    agent = _DummyAgent()
    raw = parallel_tools.multi_tool_use_parallel(
        tool_uses=[
            {
                "recipient_name": "functions.execute_console_command",
                "parameters": {"command": "git status", "timeout_seconds": 60},
            },
        ],
        agent=agent,
    )
    payload = json.loads(raw)

    assert payload["status"] == "error"
    assert "must be run directly" in payload["error"]


def test_multi_tool_use_parallel_rejects_known_slow_console_command():
    agent = _DummyAgent()
    raw = parallel_tools.multi_tool_use_parallel(
        tool_uses=[
            {
                "recipient_name": "functions.execute_console_command",
                "parameters": {"command": "python -m pytest --collect-only -q"},
            },
        ],
        agent=agent,
    )
    payload = json.loads(raw)

    assert payload["status"] == "error"
    assert "looks slow or interactive" in payload["error"]


def test_system_tools_registers_multi_tool_use_parallel():
    tool = BaseTool(_DummyAgent())
    tool.addTool("system_tools")
    assert "multi_tool_use_parallel" in tool.function_map
    assert "multi_tool_use.parallel" in tool.function_map
    assert any(
        item.get("function", {}).get("name") == "multi_tool_use_parallel"
        for item in tool.tool_declarations
    )
    assert all(
        item.get("function", {}).get("name") != "multi_tool_use.parallel"
        for item in tool.tool_declarations
    )


def test_tool_declarations_are_provider_safe_and_unique():
    tool = BaseTool(_DummyAgent())
    for name in ["system_tools", "rg_tools", "file_read_tools"]:
        tool.addTool(name)

    names = [
        item.get("function", {}).get("name")
        for item in tool.tool_declarations
        if isinstance(item, dict)
    ]
    assert names
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"^[a-zA-Z0-9_-]+$", name or "") for name in names)


def test_invalid_tool_declaration_name_is_rejected():
    module_name = "functions.invalid_protocol_name_tools"
    module = types.ModuleType(module_name)

    def invalid_tool():
        return "bad"

    module.invalid_tool_declaration = {
        "type": "function",
        "function": {"name": "invalid.tool", "parameters": {"type": "object"}},
    }
    module.__dict__["invalid.tool"] = invalid_tool
    sys.modules[module_name] = module

    try:
        tool = BaseTool(_DummyAgent())
        try:
            tool.addTool("invalid_protocol_name_tools")
        except ValueError as exc:
            assert "invalid function name" in str(exc)
        else:
            raise AssertionError("expected invalid tool declaration name to be rejected")
    finally:
        sys.modules.pop(module_name, None)


def test_missing_tool_module_raises_tool_load_error():
    tool = BaseTool(_DummyAgent())

    try:
        tool.addTool("definitely_missing_tool_module")
    except ToolLoadError as exc:
        assert "Error loading tool module definitely_missing_tool_module" in str(exc)
    else:
        raise AssertionError("expected missing tool module to raise ToolLoadError")


def test_tool_declaration_missing_function_raises_tool_load_error():
    module_name = "functions.invalid_missing_function_tools"
    module = types.ModuleType(module_name)
    module.missing_func_declaration = {
        "type": "function",
        "function": {"name": "missing_func", "parameters": {"type": "object"}},
    }
    sys.modules[module_name] = module

    try:
        tool = BaseTool(_DummyAgent())
        try:
            tool.addTool("invalid_missing_function_tools")
        except ToolLoadError as exc:
            assert "references missing function 'missing_func'" in str(exc)
        else:
            raise AssertionError("expected missing declaration function to raise ToolLoadError")
    finally:
        sys.modules.pop(module_name, None)

