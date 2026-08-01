from types import SimpleNamespace
import json

from src.providers.openai_agent import OpenAIAgent
from src.providers.responses_implementation_checkpoint import ResponsesImplementationCheckpoint
from src.runtime_policy import resolve_runtime_policy
from src.tool.base_tool import BaseTool
from src.tool.tool_call_protocol import ToolCallEnvelope
from src.tool.tool_call_protocol import ToolCallExecution


DEFAULT_RESOLVED_POLICY = resolve_runtime_policy(None)
IMPLEMENTATION_CHECKPOINT_INSTRUCTION = (
    DEFAULT_RESOLVED_POLICY.policy.implementation_checkpoint.prompt
)


def _checkpoint(limit=1):
    resolved = resolve_runtime_policy(
        {
            "overrides": {
                "implementation_checkpoint": {
                    "evidence_operation_limit": limit,
                }
            }
        }
    )
    return ResponsesImplementationCheckpoint(
        policy=resolved.policy.implementation_checkpoint
    )


def _call(name, call_id, arguments=None):
    return ToolCallEnvelope(
        name=name,
        call_id=call_id,
        arguments=arguments or {},
        arguments_json="{}",
        provider="test",
    )


def _execution(name, call_id, status="completed"):
    return ToolCallExecution(
        func_name=name,
        call_id=call_id,
        cleaned_result="{}",
        status=status,
    )


def _runtime():
    return SimpleNamespace(
        messages=[{"role": "user", "content": "fix it"}],
        RuntimeInstructionMessage=lambda content: {
            "role": "developer",
            "content": content,
        },
    )


def test_implementation_checkpoint_counts_batched_evidence_and_starts_once():
    runtime = _runtime()
    checkpoint = _checkpoint(3)
    call = _call(
        "workspace_exec",
        "call-1",
        {
            "stages": [
                {
                    "id": "inspect",
                    "operations": [
                        {"id": "a", "kind": "read_file", "arguments": {}},
                        {"id": "b", "kind": "search_text", "arguments": {}},
                        {"id": "c", "kind": "update_task_direction", "arguments": {}},
                    ],
                }
            ]
        },
    )

    assert not checkpoint.observe(
        runtime,
        function_calls=[call],
        executions=[_execution("workspace_exec", "call-1")],
    )
    assert checkpoint.evidence_operations == 2
    read_call = _call("read_file", "call-2")
    assert checkpoint.observe(
        runtime,
        function_calls=[read_call],
        executions=[_execution("read_file", "call-2")],
    )
    assert runtime.messages[-1]["content"] == IMPLEMENTATION_CHECKPOINT_INSTRUCTION
    assert not checkpoint.observe(
        runtime,
        function_calls=[read_call],
        executions=[_execution("read_file", "call-2")],
    )

    checkpoint.finish(runtime)
    assert runtime.messages == [{"role": "user", "content": "fix it"}]


def test_implementation_checkpoint_does_not_start_after_successful_patch():
    calls = [
        _call("apply_patch", "patch-1"),
        _call(
            "workspace_exec",
            "patch-2",
            {
                "stages": [
                    {
                        "id": "edit",
                        "operations": [
                            {"id": "p", "kind": "apply_patch", "arguments": {}},
                        ],
                    }
                ]
            },
        ),
    ]
    for call in calls:
        runtime = _runtime()
        checkpoint = _checkpoint()
        assert not checkpoint.observe(
            runtime,
            function_calls=[call],
            executions=[_execution(call.name, call.call_id)],
        )
        assert checkpoint.patch_seen
        assert len(runtime.messages) == 1


def test_implementation_checkpoint_restarts_for_a_completion_review_phase():
    runtime = _runtime()
    checkpoint = _checkpoint()
    patch_call = _call("apply_patch", "patch-1")
    assert not checkpoint.observe(
        runtime,
        function_calls=[patch_call],
        executions=[_execution("apply_patch", "patch-1")],
    )
    assert checkpoint.patch_seen

    checkpoint.start_phase(runtime)

    assert not checkpoint.patch_seen
    assert checkpoint.evidence_operations == 0
    read_call = _call("read_file", "read-1")
    assert checkpoint.observe(
        runtime,
        function_calls=[read_call],
        executions=[_execution("read_file", "read-1")],
    )
    assert runtime.messages[-1]["content"] == IMPLEMENTATION_CHECKPOINT_INSTRUCTION


def test_responses_loop_injects_checkpoint_then_continues_through_patch():
    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 0,
    }
    agent._agentpark_resolved_runtime_policy = resolve_runtime_policy(
        {
            "overrides": {
                "completion_review": {"enabled": False},
                "implementation_checkpoint": {"evidence_operation_limit": 1},
            }
        }
    )
    agent.provider_name = "openai"
    agent.messages = [{"role": "user", "content": "fix startup"}]
    agent.tools = BaseTool(agent)
    agent.tool_declarations = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in ("read_file", "apply_patch")
    ]
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    agent._get_messages_with_memory = lambda: list(agent.messages)
    payloads = []

    def fake_stream(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        index = len(payloads)
        if index == 1:
            return {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "read-1",
                        "name": "read_file",
                        "arguments": "{}",
                    }
                ],
            }
        if index == 2:
            return {
                "id": "resp-2",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "patch-1",
                        "name": "apply_patch",
                        "arguments": "{}",
                    }
                ],
            }
        return {
            "id": "resp-3",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "implemented"}],
                }
            ],
        }

    agent._stream_responses_with_retry = fake_stream

    def execute(calls):
        return [
            ToolCallExecution(
                func_name=call.name,
                call_id=call.call_id,
                cleaned_result='{"status":"success"}',
            )
            for call in calls
        ]

    agent._execute_tool_call_envelopes_parallel = execute
    out = agent._send_via_responses(
        messages=list(agent.messages),
        active_tools=agent.tool_declarations,
        run_tools=True,
        reasoning_effort="high",
    )

    assert out == "implemented"
    assert len(payloads) == 3
    checkpoint_texts = [
        part.get("text", "")
        for item in payloads[1]["input"]
        if item.get("type") == "message"
        for part in item.get("content", [])
    ]
    assert IMPLEMENTATION_CHECKPOINT_INSTRUCTION in checkpoint_texts
    assert [tool["name"] for tool in payloads[1]["tools"]] == [
        "read_file",
        "apply_patch",
    ]
    assert all(
        message.get("content") != IMPLEMENTATION_CHECKPOINT_INSTRUCTION
        for message in agent.messages
    )
