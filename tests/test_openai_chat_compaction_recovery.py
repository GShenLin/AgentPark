import json


def _build_openai_chat_agent():
    from src.providers.openai_agent import OpenAIAgent
    from src.tool.base_tool import BaseTool

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://chat.example/v1",
        "model": "deepseek-compatible-model",
        "responsesApi": False,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": True,
        "toolContextCompactionEveryToolCalls": 1,
        "toolContextCompactionInputTokens": 0,
        "toolContextCompactionCurrentInputTokens": 0,
        "toolContextCompactionOutputTokens": 0,
    }
    agent.provider_name = "deepseek-compatible-chat"
    agent.system_prompt = None
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.tool_declarations = [
        {
            "type": "function",
            "function": {
                "name": "execute_console_command",
                "description": "Execute a command.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    return agent


def test_chat_compaction_removes_stale_rejected_exchange_before_resuming_regular_tools():
    from src.tool.tool_call_protocol import ToolCallExecution

    agent = _build_openai_chat_agent()
    executed_commands = []
    agent.tools.function_map["execute_console_command"] = lambda **kwargs: executed_commands.append(kwargs)
    agent.messages = [
        {"role": "user", "content": "finish the current task"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_before_checkpoint",
                    "type": "function",
                    "function": {"name": "execute_console_command", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "content": "large command output",
            "tool_call_id": "call_before_checkpoint",
            "name": "execute_console_command",
        },
    ]
    requests = []

    def fake_post(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        requests.append(payload)
        if len(requests) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_rejected_during_checkpoint",
                                    "type": "function",
                                    "function": {
                                        "name": "execute_console_command",
                                        "arguments": '{"command":"Get-ChildItem"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        if len(requests) == 2:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_compact",
                                    "type": "function",
                                    "function": {
                                        "name": "compact_tool_context",
                                        "arguments": json.dumps(
                                            {
                                                "action": "replace",
                                                "reason": "Preserve the completed command result compactly.",
                                                "summary": {
                                                    "task_anchor": "Finish the current task.",
                                                    "completed_facts": ["The earlier command completed."],
                                                    "changed_state": [],
                                                    "verification": [],
                                                    "failed_attempts": [],
                                                    "remaining_steps": ["Continue the current task."],
                                                    "immediate_next_step": "Continue the current task.",
                                                    "avoid_repeating": ["Do not rerun the earlier command."],
                                                },
                                            }
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "continued"}}]}

    agent._curl_post_json_once = fake_post
    assert agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("execute_console_command", "call_before_checkpoint", "large command output")]
    )

    assert agent.Send(run_tools=True, mode="chat", stream=False) == "continued"
    assert executed_commands == []
    assert len(requests) == 3
    assert [tool["function"]["name"] for tool in requests[0]["tools"]] == ["compact_tool_context"]
    assert [tool["function"]["name"] for tool in requests[1]["tools"]] == ["compact_tool_context"]
    assert [tool["function"]["name"] for tool in requests[2]["tools"]] == ["execute_console_command"]

    retry_messages = json.dumps(requests[1]["messages"], ensure_ascii=False)
    resumed_messages = json.dumps(requests[2]["messages"], ensure_ascii=False)
    assert "call_rejected_during_checkpoint" in retry_messages
    assert "only function tool currently available" in retry_messages
    assert "call_rejected_during_checkpoint" not in resumed_messages
    assert "only function tool currently available" not in resumed_messages
    assert agent._tool_context_compaction_gate_active is False
