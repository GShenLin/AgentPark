"""Empty-response and final-response decisions for the Responses loop."""
from dataclasses import dataclass, field
from typing import Any
from src.providers.responses_runtime_support import finish_responses_message


@dataclass(frozen=True)
class ResponseLoopOutcome:
    current_input: list[Any] = field(default_factory=list)
    tools_payload: list[Any] = field(default_factory=list)
    finished: bool = False
    result: object = None


def handle_empty_response(runtime, *, empty_message_action, active_tools, tools_payload,
                          web_search_mode, response_id, request_input_item_count,
                          use_stream, emit_turn_debug):
    self, _emit_turn_debug = runtime, emit_turn_debug
    if self._tool_context_compaction_gate_active_now():
        self._retry_tool_context_compaction_gate(
            "the model returned an empty response instead of calling compact_tool_context"
        )
        tools_payload = self._build_responses_tools(
            self._tool_context_compaction_active_tools(active_tools),
            web_search_mode,
        )
        current_input = self._build_responses_input(self._get_messages_with_memory())
        _emit_turn_debug(
            response_id=response_id,
            content="",
            function_call_count=0,
            next_continuation_mode="tool_context_compaction_empty_retry",
            request_input_item_count=request_input_item_count,
            followup_item_count=0,
            stream=use_stream,
        )
        return ResponseLoopOutcome(current_input, tools_payload)
    if empty_message_action.kind == "error":
        _emit_turn_debug(
            response_id=response_id,
            content=empty_message_action.error_text,
            function_call_count=0,
            next_continuation_mode="empty_message_error",
            request_input_item_count=request_input_item_count,
            followup_item_count=0,
            stream=use_stream,
        )
        self.Message("assistant", empty_message_action.error_text)
        return ResponseLoopOutcome(finished=True, result=empty_message_action.error_text)
    current_input = empty_message_action.next_input
    _emit_turn_debug(
        response_id=response_id,
        content=empty_message_action.feedback_item["content"][0]["text"],
        function_call_count=0,
        next_continuation_mode="empty_message_feedback",
        request_input_item_count=request_input_item_count,
        followup_item_count=1,
        stream=use_stream,
    )
    return ResponseLoopOutcome(current_input, tools_payload)


def finish_response_turn(runtime, *, content, stream_text, active_tools, web_search_mode,
                         response_id, request_input_item_count, use_stream, structured_result, result, emit_turn_debug):
    self, _emit_turn_debug = runtime, emit_turn_debug
    if self._tool_context_compaction_gate_active_now():
        final_text = content or stream_text.text
        if not self._finish_tool_context_compaction_gate_with_response(final_text):
            self._retry_tool_context_compaction_gate(
                "the model returned an empty response instead of calling compact_tool_context"
            )
            tools_payload = self._build_responses_tools(
                self._tool_context_compaction_active_tools(active_tools),
                web_search_mode,
            )
            current_input = self._build_responses_input(self._get_messages_with_memory())
            _emit_turn_debug(
                response_id=response_id,
                content=final_text,
                function_call_count=0,
                next_continuation_mode="tool_context_compaction_retry",
                request_input_item_count=request_input_item_count,
                followup_item_count=0,
                stream=use_stream,
            )
            return ResponseLoopOutcome(current_input, tools_payload)

    if self._session_context_compaction_active_now():
        raise RuntimeError(
            "session context compaction required compact_session_context, but the model returned no tool call"
        )
    final_text = content or (stream_text.text if use_stream else "")
    next_continuation_mode = "final_message"
    if not content and use_stream and stream_text.text:
        next_continuation_mode = "stream_text_fallback"
    elif not content:
        next_continuation_mode = "raw_response"
    _emit_turn_debug(
        response_id=response_id,
        content=content or stream_text.text,
        function_call_count=0,
        next_continuation_mode=next_continuation_mode,
        request_input_item_count=request_input_item_count,
        followup_item_count=0,
        stream=use_stream,
    )
    finished = finish_responses_message(
        self,
        content=content,
        stream_text=stream_text.text if use_stream else "",
        structured_result=structured_result,
        raw_result=result,
    )
    self._close_current_agent_step(reason="assistant_final")
    return ResponseLoopOutcome(finished=True, result=finished)
