import json
import os
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("AGENTPARK_RUN_KRILL_RESPONSES_LIVE") != "1",
    reason="live Krill Responses multi-tool continuation test is opt-in",
)


def test_krill_responses_websocket_continuation_preserves_five_tool_call_task():
    from src.providers.openai_agent import OpenAIAgent
    from src.tool.base_tool import BaseTool

    agent = OpenAIAgent(provider_id="krill_gpt55", internal_memory_enabled=False)
    agent.config = dict(agent.config)
    agent.config["responsesReplayReasoningItems"] = False
    agent.config["toolContextCompactionEnabled"] = False
    agent.config["reasoningEffort"] = "low"
    agent.tools = BaseTool(agent)
    observed_calls = []
    websocket_payloads = []

    declaration = {
        "type": "function",
        "function": {
            "name": "record_probe_call",
            "description": (
                "Record one required continuation probe call. Call this exactly once per model turn "
                "with the next index until all five calls are complete."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "The 1-based probe call index. Use 1, then 2, then 3, then 4, then 5.",
                    }
                },
                "required": ["index"],
                "additionalProperties": False,
            },
        },
    }

    def record_probe_call(index=None):
        observed_calls.append(index)
        return json.dumps(
            {
                "status": "continue" if len(observed_calls) < 5 else "complete",
                "received_index": index,
                "observed_count": len(observed_calls),
                "required_count": 5,
                "next_index": len(observed_calls) + 1 if len(observed_calls) < 5 else None,
                "instruction": (
                    "If status is continue, call record_probe_call again and do not send a final answer. "
                    "If status is complete, answer KRILL_TOOL_LOOP_DONE: 1,2,3,4,5."
                ),
            },
            ensure_ascii=False,
        )

    agent.tools.register_external_tool(declaration, record_probe_call)
    real_connection_factory = agent._responses_websocket_connection
    recording_connection = None

    class RecordingConnection:
        def __init__(self, connection):
            self.connection = connection

        def send(self, message):
            websocket_payloads.append(json.loads(message))
            return self.connection.send(message)

        def recv(self, timeout=None):
            return self.connection.recv(timeout=timeout)

        def close(self):
            return self.connection.close()

    def get_recording_connection(**kwargs):
        nonlocal recording_connection
        if recording_connection is None:
            recording_connection = RecordingConnection(real_connection_factory(**kwargs))
        return recording_connection

    agent._responses_websocket_connection = get_recording_connection

    prompt = (
        "Call the tool five times. You are testing tool continuation. You must call record_probe_call exactly "
        "five times, one at a time, with index 1 then 2 then 3 then 4 then 5. Never answer while "
        "the latest tool result has status continue. After status complete, answer exactly: "
        "KRILL_TOOL_LOOP_DONE: 1,2,3,4,5"
    )
    try:
        result = agent._send_via_responses(
            messages=[{"role": "user", "content": prompt}],
            active_tools=agent.tools.tool_declarations,
            run_tools=True,
            reasoning_effort="low",
        )
    finally:
        agent._close_responses_websocket()

    assert observed_calls == [1, 2, 3, 4, 5]
    assert "KRILL_TOOL_LOOP_DONE: 1,2,3,4,5" in result
    assert len(websocket_payloads) >= 6
    assert "previous_response_id" not in websocket_payloads[0]
    first_input_types = [item.get("type") for item in websocket_payloads[0].get("input", [])]
    assert first_input_types
    assert set(first_input_types) == {"message"}
    for payload in websocket_payloads[1:]:
        assert payload.get("previous_response_id")
        input_items = payload.get("input")
        assert isinstance(input_items, list)
        assert [item.get("type") for item in input_items] == ["function_call_output"]
        assert all("id" not in item for item in input_items)


def test_krill_responses_websocket_can_inspect_project_with_a_tool():
    from src.providers.openai_agent import OpenAIAgent
    from src.tool.base_tool import BaseTool

    project_root = Path(__file__).resolve().parents[1]
    agent = OpenAIAgent(provider_id="krill_gpt55", internal_memory_enabled=False)
    agent.config = dict(agent.config)
    agent.config["responsesReplayReasoningItems"] = False
    agent.config["toolContextCompactionEnabled"] = False
    agent.config["reasoningEffort"] = "low"
    agent.tools = BaseTool(agent)
    tool_reports = []
    websocket_payloads = []

    declaration = {
        "type": "function",
        "function": {
            "name": "inspect_project",
            "description": "Read the current AgentPark project status and source layout. This tool is read-only.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    }

    def inspect_project():
        status_lines = subprocess.run(
            ["git", "status", "--short"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        python_files = list((project_root / "src").rglob("*.py")) + list((project_root / "tests").rglob("*.py"))
        transport_path = project_root / "src" / "providers" / "responses_websocket_transport.py"
        report = {
            "probe": "PROJECT_INSPECTION_OK",
            "branch": branch,
            "changed_paths": len(status_lines),
            "python_files": len(python_files),
            "responses_websocket_transport_lines": len(transport_path.read_text(encoding="utf-8").splitlines()),
        }
        tool_reports.append(report)
        return json.dumps(report, ensure_ascii=False)

    agent.tools.register_external_tool(declaration, inspect_project)
    real_connection_factory = agent._responses_websocket_connection
    recording_connection = None

    class RecordingConnection:
        def __init__(self, connection):
            self.connection = connection

        def send(self, message):
            websocket_payloads.append(json.loads(message))
            return self.connection.send(message)

        def recv(self, timeout=None):
            return self.connection.recv(timeout=timeout)

        def close(self):
            return self.connection.close()

    def get_recording_connection(**kwargs):
        nonlocal recording_connection
        if recording_connection is None:
            recording_connection = RecordingConnection(real_connection_factory(**kwargs))
        return recording_connection

    agent._responses_websocket_connection = get_recording_connection
    prompt = (
        "Use inspect_project exactly once. Then summarize the returned project facts in one concise sentence. "
        "Your answer must include PROJECT_INSPECTION_OK and the exact branch, changed_paths, python_files, "
        "and responses_websocket_transport_lines values returned by the tool."
    )
    try:
        result = agent._send_via_responses(
            messages=[{"role": "user", "content": prompt}],
            active_tools=agent.tools.tool_declarations,
            run_tools=True,
            reasoning_effort="low",
        )
    finally:
        agent._close_responses_websocket()

    assert len(tool_reports) == 1
    report = tool_reports[0]
    assert "PROJECT_INSPECTION_OK" in result
    assert report["branch"] in result
    for field in ("changed_paths", "python_files", "responses_websocket_transport_lines"):
        assert str(report[field]) in result
    assert len(websocket_payloads) == 2
    continuation = websocket_payloads[1]
    assert continuation.get("previous_response_id")
    assert [item.get("type") for item in continuation.get("input", [])] == ["function_call_output"]
    assert all("id" not in item for item in continuation["input"])
