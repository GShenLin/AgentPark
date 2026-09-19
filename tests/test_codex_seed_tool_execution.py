import io
import json
import shutil

import pytest

from nodes.codex_node.runtime.live_bridge import CodexLiveBridge
from src.harness.responses_gateway import HarnessResponsesGateway
from nodes.codex_node.runtime.session_manager import CodexSessionManager, CodexSessionSpec
from src.cli_provider_runtime.http_transport import UpstreamResponse


@pytest.mark.skipif(shutil.which("codex") is None and shutil.which("codex.cmd") is None, reason="Codex CLI is not installed")
@pytest.mark.parametrize("native_function", [False, True])
def test_real_codex_executes_two_seed_commands_and_returns_results(tmp_path, monkeypatch, native_function):
    config_path = tmp_path / "providers.json"
    config_path.write_text(json.dumps({"providers": {"seed-mock": {
        "type": "doubao", "baseUrl": "http://unused.invalid/v3", "apiKey": "test",
        "model": "doubao-seed-evolving", "responsesApi": True, "supportmode": ["chat"],
        "toolResultSubmissionMaxChars": 50000, "toolContextCompactionEnabled": False,
    }}}), encoding="utf-8")
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    requests = []

    def upstream(_config, payload, **_kwargs):
        requests.append(payload)
        assert not any(item.get("type") in {"additional_tools", "custom_tool_call", "custom_tool_call_output"} for item in payload["input"])
        assert not any(tool.get("type") == "custom" for tool in payload["tools"])
        assert any(tool.get("name") == "exec" and tool.get("type") == "function" for tool in payload["tools"])
        if len(requests) > 2:
            raise AssertionError("Seed normalization caused an unexpected extra model request.")
        text = "SEED_EXECUTION_FINISHED"
        if len(requests) == 1:
            text = "检查命令执行。<seed:tool_call>" + ''.join(
                '<function name="exec_command"><parameter name="cmd" string">'
                f"Write-Output '{marker}'</parameter></function>"
                for marker in ["SEED_COMMAND_FIRST", "SEED_COMMAND_SECOND"]
            ) + "</seed:tool_call>"
        item = {"type": "message", "id": f"msg_seed_{len(requests)}", "role": "assistant",
                "status": "completed", "content": [{"type": "output_text", "text": text}]}
        events = [
            {"type": "response.created", "response": {"id": f"resp_seed_{len(requests)}"}},
            {"type": "response.output_item.added", "output_index": 0,
             "item": {**item, "status": "in_progress", "content": []}},
        ]
        events.extend({"type": "response.output_text.delta", "output_index": 0,
                       "item_id": item["id"], "content_index": 0, "delta": text[pos:pos + 7]}
                      for pos in range(0, len(text), 7))
        events.extend([
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": f"resp_seed_{len(requests)}",
             "status": "completed", "output": [item], "usage": {
                 "input_tokens": 10, "output_tokens": 20, "total_tokens": 30,
             }}},
        ])
        if len(requests) == 1 and native_function:
            executor = next(tool for tool in payload["tools"] if tool.get("name") == "exec")
            nested = "exec_command" if "exec_command(args:" in executor["description"] else "shell_command"
            key = "cmd" if nested == "exec_command" else "command"
            items = []
            events = [events[0]]
            for index, marker in enumerate(["SEED_COMMAND_FIRST", "SEED_COMMAND_SECOND"]):
                source = f"text(await tools.{nested}({json.dumps({key: f'Write-Output {marker}'})}));"
                args = json.dumps({"input": source})
                call = {"type": "function_call", "name": "exec", "id": f"fc_{index}",
                        "call_id": f"call_{index}", "arguments": args, "status": "completed"}
                items.append(call)
                events.append({"type": "response.output_item.added", "output_index": index,
                               "item": {**call, "status": "in_progress", "arguments": ""}})
                events.extend({"type": "response.function_call_arguments.delta", "output_index": index,
                               "item_id": call["id"], "delta": args[pos:pos + 5]} for pos in range(0, len(args), 5))
                events.append({"type": "response.function_call_arguments.done", "output_index": index,
                               "item_id": call["id"], "arguments": args})
                events.append({"type": "response.output_item.done", "output_index": index, "item": call})
            events.append({"type": "response.completed", "response": {
                "id": "resp_seed_1", "status": "completed", "output": items,
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            }})
        body = ''.join('event: ' + event["type"] + '\ndata: ' + json.dumps(event) + '\n\n' for event in events).encode()
        return UpstreamResponse(200, {"content-type": "text/event-stream"}, io.BytesIO(body))

    # No request reaches a paid model; only the real Codex tool executor runs.
    monkeypatch.setattr("src.cli_provider_runtime.gateway_dispatch._open_responses", upstream)
    gateway = HarnessResponsesGateway()
    manager = CodexSessionManager(gateway=gateway)
    events = []
    bridge = CodexLiveBridge(events.append)
    try:
        result = manager.run_turn(CodexSessionSpec(
            session_key="seed-execution-test", provider_id="seed-mock", model="doubao-seed-evolving",
            command="codex", cwd=str(tmp_path), sandbox="danger-full-access",
            state_path=str(tmp_path / "session.json"), reasoning_effort="high",
        ), "Execute the two harmless Write-Output commands and then finish.", event_handler=bridge.handle)
    finally:
        manager.close_all()
        gateway.close()

    assert result.endswith("SEED_EXECUTION_FINISHED")
    if not native_function:
        assert any(event.get("type") == "node_message_delta" and "检查命令执行" in json.dumps(event, ensure_ascii=False) for event in events)
    assert len(requests) == 2
    tool_outputs = [item for item in requests[1]["input"] if item.get("type") in {
        "custom_tool_call_output", "function_call_output",
    }]
    assert len(tool_outputs) == 2
    assert all(item["type"] == "function_call_output" for item in tool_outputs)
    history_calls = [item for item in requests[1]["input"] if item.get("type") == "function_call"]
    assert len(history_calls) == 2
    assert all(isinstance(json.loads(item["arguments"])["input"], str) for item in history_calls)
    actual_results = [json.dumps(item["output"], ensure_ascii=False) for item in tool_outputs]
    assert any("SEED_COMMAND_FIRST" in text for text in actual_results)
    assert any("SEED_COMMAND_SECOND" in text for text in actual_results)
    assert all("not defined" not in text and "is not a function" not in text for text in actual_results)
    assistant_messages = [item for item in requests[1]["input"] if item.get("role") == "assistant"]
    assert "<seed:tool_call>" not in json.dumps(assistant_messages)
    assert sum(event.get("type") == "tool_call_end" and event.get("status") == "completed" for event in events) >= 2
