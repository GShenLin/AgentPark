from src.tool.tool_call_protocol import ToolCallEnvelope
from src.tool_turn_admission import admit_tool_turn


def _call(name: str, call_id: str) -> ToolCallEnvelope:
    return ToolCallEnvelope(
        name=name,
        call_id=call_id,
        arguments={},
        arguments_json="{}",
        provider="test",
    )


def test_normal_tool_turn_admits_every_normalized_call():
    calls = [_call("read_file", "read-1"), _call("rg_search_text", "search-1")]

    decision = admit_tool_turn(calls, compaction_gate_active=False)

    assert decision.admitted_calls == tuple(calls)
    assert decision.rejected_calls == ()
    assert decision.retry_required is False
    assert decision.provider_continuation_safe is True


def test_compaction_turn_admits_only_the_checkpoint_call_from_a_mixed_batch():
    compact = _call("compact_tool_context", "compact-1")
    calls = [compact, _call("execute_console_command", "shell-1"), _call("read_file", "read-1")]

    decision = admit_tool_turn(calls, compaction_gate_active=True)

    assert decision.admitted_calls == (compact,)
    assert [(item.name, item.reason) for item in decision.rejected_calls] == [
        ("execute_console_command", "not_offered_during_compaction"),
        ("read_file", "not_offered_during_compaction"),
    ]
    assert decision.retry_required is False
    assert decision.provider_continuation_safe is False


def test_compaction_turn_retries_when_the_model_only_calls_unoffered_tools():
    decision = admit_tool_turn(
        [_call("execute_console_command", "shell-1")],
        compaction_gate_active=True,
    )

    assert decision.admitted_calls == ()
    assert decision.retry_required is True
    assert decision.provider_continuation_safe is False


def test_compaction_turn_executes_at_most_one_compaction_call():
    first = _call("compact_tool_context", "compact-1")
    second = _call("compact_tool_context", "compact-2")

    decision = admit_tool_turn([first, second], compaction_gate_active=True)

    assert decision.admitted_calls == (first,)
    assert [(item.call_id, item.reason) for item in decision.rejected_calls] == [
        ("compact-2", "duplicate_compaction_call")
    ]

