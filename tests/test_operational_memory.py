import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.base_agent import BaseAgent
from src.operational_memory import build_operational_memory_summary
from src.operational_memory import OperationalMemoryError
from src.operational_memory import record_operational_memory_entry
from src.operational_memory_tool import record_operational_memory
from src.operational_memory_tool import record_operational_memory_declaration
from src.tool.tool_call_protocol import ToolCallExecution


class DummyAgent(BaseAgent):
    def __init__(self, memory_path):
        super().__init__("dummy", memory_file_path=str(memory_path), internal_memory_enabled=False)
        self.operational_memory_gate_enabled = True
        self.sent_tools = []

    def Send(self, tools=None, run_tools=True, mode="chat", stream=False):
        self.sent_tools.append(tools)
        result = self.tools.execute_tool(
            "record_operational_memory",
            {
                "action": "upsert",
                "reason": "The failure exposes a reusable environment constraint.",
                "kind": "environment_fact",
                "title": "Use PowerShell-compatible commands",
                "lesson": "Use PowerShell-compatible commands in this workspace.",
                "evidence": "A bash-only command failed in the active shell.",
                "scope": {"project": "C:\\Project\\AgentPark", "shell": "powershell"},
                "tool_name": "execute_console_command",
                "error": "bash heredoc syntax failed",
                "avoid": ["cat <<EOF"],
                "prefer": ["PowerShell here-strings", "rg"],
                "confidence": "high",
            },
        )
        self.Message("tool", result, persist=False, tool_call_id="memory-gate", name="record_operational_memory")
        return result


class DummyAgentWithoutMemoryRecord(DummyAgent):
    def Send(self, tools=None, run_tools=True, mode="chat", stream=False):
        self.sent_tools.append(tools)
        self.Message("assistant", "Continuing without recording operational memory.", persist=False)
        return "Continuing without recording operational memory."


class DummyAgentRecordsOnSecondAttempt(DummyAgent):
    def Send(self, tools=None, run_tools=True, mode="chat", stream=False):
        if not self.sent_tools:
            self.sent_tools.append(tools)
            self.Message("assistant", "Continuing without recording operational memory.", persist=False)
            return "Continuing without recording operational memory."
        return super().Send(tools=tools, run_tools=run_tools, mode=mode, stream=stream)


def test_record_operational_memory_upserts_and_summarizes(tmp_path):
    path = tmp_path / "operational_memory.json"

    first = record_operational_memory_entry(
        path=str(path),
        action="upsert",
        reason="reusable",
        kind="tool_limitation",
        title="Use rg instead of grep",
        lesson="Use rg for repository search in this workspace.",
        evidence="grep command failed while rg is available.",
        scope={"project": "C:\\Project\\AgentPark"},
        tool_name="execute_console_command",
        error="grep not found",
        avoid=["grep -r"],
        prefer=["rg"],
        confidence="high",
    )
    second = record_operational_memory_entry(
        path=str(path),
        action="upsert",
        reason="same lesson repeated",
        kind="tool_limitation",
        title="Use rg instead of grep",
        lesson="Use rg for repository search in this workspace.",
        evidence="grep command failed again.",
        scope={"project": "C:\\Project\\AgentPark"},
        tool_name="execute_console_command",
        error="grep failed",
        avoid=["grep -r"],
        prefer=["rg"],
        confidence="high",
    )

    assert first["key"] == second["key"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    item = payload["memories"][first["key"]]
    assert item["count"] == 2
    assert item["status"] == "active"
    summary = build_operational_memory_summary(str(path))
    assert "Use rg instead of grep" in summary
    assert "Prefer: rg" in summary


def test_record_operational_memory_does_not_notify_companion_inbox(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    companion_config = graphs_dir / "companion" / "config.json"
    companion_config.parent.mkdir(parents=True)
    companion_config.write_text(
        json.dumps({"graph_id": "companion", "type_id": "agent_node"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))

    memory_path = graphs_dir / "default" / "Agent1" / "memory.md"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text("", encoding="utf-8")
    agent = DummyAgent(memory_path)
    agent._agentpark_graph_id = "default"
    agent._agentpark_node_id = "Agent1"
    agent._agentpark_node_type_id = "agent_node"

    result = json.loads(
        record_operational_memory(
            action="upsert",
            reason="The failure is reusable.",
            kind="tool_limitation",
            title="Use PowerShell commands",
            lesson="Use PowerShell-compatible syntax in this workspace.",
            evidence="Bash heredoc syntax failed in PowerShell.",
            scope={"project": "D:\\Project\\AgentPark"},
            tool_name="execute_console_command",
            error="bash heredoc syntax failed",
            confidence="high",
            agent=agent,
        )
    )

    assert result["ok"] is True
    assert not (companion_config.parent / "inbox.jsonl").exists()
    assert not (companion_config.parent / "messages.jsonl").exists()


def test_record_operational_memory_skip_does_not_notify_companion(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    companion_config = graphs_dir / "companion" / "config.json"
    companion_config.parent.mkdir(parents=True)
    companion_config.write_text(
        json.dumps({"graph_id": "companion", "type_id": "agent_node"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))

    memory_path = graphs_dir / "default" / "Agent1" / "memory.md"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text("", encoding="utf-8")
    agent = DummyAgent(memory_path)
    agent._agentpark_graph_id = "default"
    agent._agentpark_node_id = "Agent1"

    result = json.loads(
        record_operational_memory(
            action="skip",
            reason="No long-term lesson.",
            tool_name="execute_console_command",
            error="temporary",
            agent=agent,
        )
    )

    assert result["ok"] is True
    assert result["action"] == "skip"
    assert not (companion_config.parent / "inbox.jsonl").exists()


def test_companion_operational_memory_does_not_notify_itself(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    companion_config = graphs_dir / "companion" / "config.json"
    companion_config.parent.mkdir(parents=True)
    companion_config.write_text(
        json.dumps({"graph_id": "companion", "type_id": "agent_node"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))

    memory_path = graphs_dir / "companion" / "memory.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyAgent(memory_path)
    agent._agentpark_graph_id = "companion"
    agent._agentpark_node_id = "companion"

    result = json.loads(
        record_operational_memory(
            action="upsert",
            reason="The failure is reusable.",
            kind="tool_limitation",
            title="Run Slow Console Commands Directly",
            lesson="Run slow console commands directly instead of through parallel wrappers.",
            evidence="A slow command was rejected by the parallel wrapper.",
            scope={"tool": "multi_tool_use_parallel"},
            tool_name="multi_tool_use_parallel",
            error="slow command rejected",
            confidence="high",
            agent=agent,
        )
    )

    assert result["ok"] is True
    assert result["action"] == "upsert"
    assert not (companion_config.parent / "inbox.jsonl").exists()


def test_companion_operational_memory_path_fallback_does_not_notify_itself(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    companion_config = graphs_dir / "companion" / "config.json"
    companion_config.parent.mkdir(parents=True)
    companion_config.write_text(
        json.dumps({"graph_id": "companion", "type_id": "agent_node"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))

    memory_path = graphs_dir / "companion" / "memory.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyAgent(memory_path)

    result = json.loads(
        record_operational_memory(
            action="upsert",
            reason="The failure is reusable.",
            kind="tool_limitation",
            title="Run Slow Console Commands Directly",
            lesson="Run slow console commands directly instead of through parallel wrappers.",
            evidence="A slow command was rejected by the parallel wrapper.",
            scope={"tool": "multi_tool_use_parallel"},
            tool_name="multi_tool_use_parallel",
            error="slow command rejected",
            confidence="high",
            agent=agent,
        )
    )

    assert result["ok"] is True
    assert result["action"] == "upsert"
    assert not (companion_config.parent / "inbox.jsonl").exists()


def test_record_operational_memory_without_node_identity_does_not_notify_companion(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    companion_config = graphs_dir / "companion" / "config.json"
    companion_config.parent.mkdir(parents=True)
    companion_config.write_text(
        json.dumps({"graph_id": "companion", "type_id": "agent_node"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))

    memory_path = tmp_path / "standalone-worker.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyAgent(memory_path)

    result = json.loads(
        record_operational_memory(
            action="upsert",
            reason="The failure is reusable.",
            kind="tool_limitation",
            title="Use PowerShell commands",
            lesson="Use PowerShell-compatible syntax in this workspace.",
            evidence="Bash heredoc syntax failed in PowerShell.",
            scope={"project": "D:\\Project\\AgentPark"},
            tool_name="execute_console_command",
            error="bash heredoc syntax failed",
            confidence="high",
            agent=agent,
        )
    )

    assert result["ok"] is True
    assert not (companion_config.parent / "inbox.jsonl").exists()


def test_record_operational_memory_keeps_original_result(tmp_path):
    memory_path = tmp_path / "agent" / "agent.md"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text("", encoding="utf-8")
    agent = DummyAgent(memory_path)
    agent._agentpark_graph_id = "default"
    agent._agentpark_node_id = "Agent1"

    result = json.loads(
        record_operational_memory(
            action="upsert",
            reason="The failure is reusable.",
            kind="tool_limitation",
            title="Use PowerShell commands",
            lesson="Use PowerShell-compatible syntax in this workspace.",
            evidence="Bash heredoc syntax failed in PowerShell.",
            scope={"project": "D:\\Project\\AgentPark"},
            tool_name="demo_tool",
            error="bash heredoc syntax failed",
            confidence="high",
            agent=agent,
        )
    )

    assert result["ok"] is True
    assert result["action"] == "upsert"
    assert result["path"] == str(memory_path.parent / "operational_memory.json")


def test_record_operational_memory_without_companion_keeps_original_result(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "missing-memories"))
    memory_path = tmp_path / "agent" / "agent.md"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text("", encoding="utf-8")
    agent = DummyAgent(memory_path)
    agent._agentpark_graph_id = "default"
    agent._agentpark_node_id = "Agent1"

    result = json.loads(
        record_operational_memory(
            action="skip",
            reason="No long-term lesson.",
            tool_name="demo_tool",
            error="temporary",
            agent=agent,
        )
    )

    assert result == {
        "ok": True,
        "action": "skip",
        "reason": "No long-term lesson.",
        "path": str(memory_path.parent / "operational_memory.json"),
    }
    assert not (tmp_path / "missing-memories").exists()


def test_operational_memory_summary_reports_invalid_file(tmp_path):
    path = tmp_path / "operational_memory.json"
    path.write_text("{not json}", encoding="utf-8")

    with pytest.raises(OperationalMemoryError, match="failed to read operational memory"):
        build_operational_memory_summary(str(path))


def test_record_operational_memory_declaration_has_action_specific_schema():
    params = record_operational_memory_declaration["function"]["parameters"]
    branches = params.get("oneOf")
    assert isinstance(branches, list)
    branch_by_action = {
        item["properties"]["action"]["enum"][0]: item
        for item in branches
        if isinstance(item, dict)
        and isinstance(item.get("properties"), dict)
        and isinstance(item["properties"].get("action"), dict)
    }

    assert set(branch_by_action) == {"upsert", "replace", "resolve", "skip"}
    assert set(branch_by_action["upsert"]["required"]) >= {
        "action",
        "reason",
        "kind",
        "title",
        "lesson",
        "evidence",
        "scope",
        "confidence",
    }
    assert "memories" in branch_by_action["replace"]["required"]
    assert branch_by_action["resolve"]["anyOf"] == [{"required": ["key"]}, {"required": ["resolve_key"]}]
    assert branch_by_action["skip"]["required"] == ["action", "reason"]


def test_concurrent_operational_memory_upserts_keep_count(tmp_path):
    path = tmp_path / "operational_memory.json"

    def upsert(index):
        return record_operational_memory_entry(
            path=str(path),
            action="upsert",
            reason=f"repeat {index}",
            kind="tool_limitation",
            title="Use rg instead of grep",
            lesson="Use rg for repository search in this workspace.",
            evidence=f"grep command failed {index}.",
            scope={"project": "C:\\Project\\AgentPark"},
            tool_name="execute_console_command",
            error=f"grep failed {index}",
            avoid=["grep -r"],
            prefer=["rg"],
            confidence="high",
        )

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(upsert, range(40)))

    keys = {item["key"] for item in results}
    assert len(keys) == 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    item = payload["memories"][next(iter(keys))]
    assert item["count"] == 40
    assert len(item["failure_samples"]) == 3
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_tool_execution_triggers_memory_gate(tmp_path):
    memory_path = tmp_path / "agent" / "agent.md"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text("", encoding="utf-8")
    agent = DummyAgent(memory_path)

    ran = agent._run_operational_memory_gate_for_failed_executions(
        [
            ToolCallExecution(
                func_name="execute_console_command",
                call_id="call-1",
                cleaned_result='{"status":"error","error":"bash heredoc syntax failed"}',
                status="error",
                error="bash heredoc syntax failed",
            )
        ]
    )

    assert ran is True
    assert agent.sent_tools
    declarations = agent.sent_tools[0]
    assert isinstance(declarations, list)
    assert [item["function"]["name"] for item in declarations] == ["record_operational_memory"]
    memory_file = memory_path.parent / "operational_memory.json"
    payload = json.loads(memory_file.read_text(encoding="utf-8"))
    assert len(payload["memories"]) == 1
    item = next(iter(payload["memories"].values()))
    assert item["tool_name"] == "execute_console_command"
    assert item["confidence"] == "high"


def test_failed_tool_execution_memory_gate_allows_no_record(tmp_path):
    memory_path = tmp_path / "agent" / "agent.md"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text("", encoding="utf-8")
    agent = DummyAgentWithoutMemoryRecord(memory_path)

    ran = agent._run_operational_memory_gate_for_failed_executions(
        [
            ToolCallExecution(
                func_name="execute_console_command",
                call_id="call-1",
                cleaned_result='{"status":"error","error":"transient failure"}',
                status="error",
                error="transient failure",
            )
        ]
    )

    assert ran is False
    assert len(agent.sent_tools) == 2
    assert any(
        item.get("role") == "system"
        and "Error: RuntimeError: operational memory gate did not call record_operational_memory" in item.get("content", "")
        for item in agent.messages
        if isinstance(item, dict)
    )
    assert not (memory_path.parent / "operational_memory.json").exists()
    assert "record_operational_memory" not in agent.tools.function_map


def test_failed_tool_execution_memory_gate_retries_after_missing_record_call(tmp_path):
    memory_path = tmp_path / "agent" / "agent.md"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text("", encoding="utf-8")
    agent = DummyAgentRecordsOnSecondAttempt(memory_path)

    ran = agent._run_operational_memory_gate_for_failed_executions(
        [
            ToolCallExecution(
                func_name="execute_console_command",
                call_id="call-1",
                cleaned_result='{"status":"error","error":"bash heredoc syntax failed"}',
                status="error",
                error="bash heredoc syntax failed",
            )
        ]
    )

    assert ran is True
    assert len(agent.sent_tools) == 2
    feedback_index = next(
        index
        for index, item in enumerate(agent.messages)
        if isinstance(item, dict)
        and item.get("role") == "system"
        and "Error: RuntimeError: operational memory gate did not call record_operational_memory" in item.get("content", "")
    )
    tool_index = next(
        index
        for index, item in enumerate(agent.messages)
        if isinstance(item, dict) and item.get("role") == "tool" and item.get("name") == "record_operational_memory"
    )
    assert feedback_index < tool_index
    assert (memory_path.parent / "operational_memory.json").exists()


def test_operational_memory_gate_restores_existing_function_map_entry(tmp_path):
    memory_path = tmp_path / "agent" / "agent.md"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text("", encoding="utf-8")
    agent = DummyAgentWithoutMemoryRecord(memory_path)
    sentinel = object()
    agent.tools.function_map["record_operational_memory"] = sentinel

    ran = agent._run_operational_memory_gate_for_failed_executions(
        [
            ToolCallExecution(
                func_name="execute_console_command",
                call_id="call-1",
                cleaned_result='{"status":"error","error":"transient failure"}',
                status="error",
                error="transient failure",
            )
        ]
    )

    assert ran is False
    assert agent.tools.function_map["record_operational_memory"] is sentinel


def test_operational_memory_replace_rewrites_corrected_set(tmp_path):
    path = tmp_path / "operational_memory.json"
    record_operational_memory_entry(
        path=str(path),
        action="upsert",
        reason="seed",
        kind="tool_limitation",
        title="Bad old lesson",
        lesson="Old lesson.",
        evidence="old evidence",
        scope={"project": "C:\\Project\\AgentPark"},
        tool_name="demo_tool",
    )

    result = record_operational_memory_entry(
        path=str(path),
        action="replace",
        reason="correct stale memory",
        memories={
            "corrected-key": {
                "kind": "environment_fact",
                "scope": {"project": "C:\\Project\\AgentPark"},
                "tool_name": "execute_console_command",
                "title": "Use PowerShell syntax",
                "lesson": "Prefer PowerShell-compatible commands.",
                "evidence": "The active shell is PowerShell.",
                "prefer": ["Get-Content"],
                "avoid": ["cat <<EOF"],
                "confidence": "high",
                "status": "active",
            }
        },
    )

    assert result["action"] == "replace"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert list(payload["memories"].keys()) == ["corrected-key"]
    assert payload["memories"]["corrected-key"]["lesson"] == "Prefer PowerShell-compatible commands."


def test_gate_prompt_includes_full_current_operational_memory(tmp_path):
    memory_path = tmp_path / "agent" / "agent.md"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text("", encoding="utf-8")
    memory_file = memory_path.parent / "operational_memory.json"
    record_operational_memory_entry(
        path=str(memory_file),
        action="upsert",
        reason="seed",
        kind="environment_fact",
        title="Existing environment fact",
        lesson="Existing full lesson visible to gate.",
        evidence="seed evidence",
        scope={"project": "C:\\Project\\AgentPark"},
        tool_name="demo_tool",
    )
    agent = DummyAgent(memory_path)

    prompt = agent._build_operational_memory_gate_prompt(
        [
            {
                "tool_name": "demo_tool",
                "call_id": "call-1",
                "status": "error",
                "error": "boom",
                "result_preview": "{}",
            }
        ]
    )

    assert "Current operational memory:" in prompt
    assert "Existing full lesson visible to gate." in prompt
    assert "record_operational_memory exactly once" in prompt
    assert "required even when no memory is worth recording" in prompt
    assert "action=replace" in prompt
    assert "action=skip" in prompt
