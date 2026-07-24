import json
from functools import partial
from typing import Any

from src.providers.agent_context_history import load_agent_context_history
from src.providers.agent_context_history import save_agent_context_history
from src.providers.agent_turn_context import load_agent_turn_context_reference
from src.providers.agent_turn_context import save_agent_turn_context_reference
from src.providers.mid_turn_user_inputs import consume_mid_turn_user_messages
from src.providers.responses_runtime_context import build_responses_agent_environment_context
from src.providers.responses_runtime_context import build_responses_turn_context
from src.providers.responses_runtime_context import runtime_context_history_items
from src.providers.responses_empty_message import EmptyMessageFeedbackController
from src.providers.responses_completed_tool_checkpoint import CompletedToolContextCheckpoint
from src.providers.responses_completed_tool_checkpoint import completed_tool_checkpoint_enabled
from src.providers.responses_item_runtime import ResponsesItemLevelToolRunner
from src.providers.responses_runtime_request import build_and_emit_responses_request_payload
from src.providers.responses_runtime_mode import resolve_responses_runtime_mode
from src.providers.responses_runtime_protocol import ResponsesStreamText
from src.providers.responses_runtime_support import ResponsesStreamCallbacks
from src.providers.responses_runtime_support import ResponsesStructuredResultAccumulator
from src.providers.responses_runtime_support import abort_responses_item_tool_runner
from src.providers.responses_runtime_support import checkpoint_completed_tool_context
from src.providers.responses_runtime_support import close_responses_item_tool_runner
from src.providers.responses_runtime_support import consume_responses_mid_turn_input_items
from src.providers.responses_runtime_support import emit_responses_turn_debug
from src.providers.responses_runtime_support import finish_responses_message
from src.providers.tool_call_execution import execute_tool_call_items_parallel
from src.runtime_cancellation import CancellationRequested
from src.tool.tool_call_protocol import to_openai_tool_call

def send_via_responses(
    runtime,
    *,
    messages,
    active_tools,
    run_tools,
    regular_active_tools=None,
    web_search_mode="disabled",
    stream_handler=None,
    thinking_stream_handler=None,
    **provider_options,
):
    self = runtime
    url, headers = self._responses_request_target()
    if regular_active_tools is None:
        regular_active_tools = active_tools
    tools_payload = self._build_responses_tools(
        active_tools,
        web_search_mode,
    )
    current_input = self._build_responses_input(messages)
    explicit_context_input = list(current_input)
    stream_text = ResponsesStreamText()
    mode_decision = resolve_responses_runtime_mode(self)
    use_item_level_mode = mode_decision.mode == "item_level"
    use_stream, empty_message_feedback, request_index = (
        callable(stream_handler) or callable(thinking_stream_handler) or use_item_level_mode,
        EmptyMessageFeedbackController(),
        0,
    )
    model_reference_context_item: dict[str, Any] | None = None
    persistent_reference_context_item = load_agent_turn_context_reference(self)
    context_history_items = runtime_context_history_items(load_agent_context_history(self))
    context_history_items_to_save, sticky_request_instructions = list(context_history_items), ""
    completed_tool_checkpoint = CompletedToolContextCheckpoint(
        enabled=completed_tool_checkpoint_enabled(self)
    )
    if callable(reset_loop_guard := getattr(self, "_reset_tool_call_loop_guard", None)):
        reset_loop_guard()
    last_request_summary: dict[str, Any] | None = None
    structured_result_accumulator = ResponsesStructuredResultAccumulator()
    self._last_responses_structured_result = {}
    thinking_text = ResponsesStreamText()
    stream_callbacks = ResponsesStreamCallbacks(
        runtime=self,
        stream_handler=stream_handler,
        thinking_stream_handler=thinking_stream_handler,
        stream_text=stream_text,
        thinking_text=thinking_text,
    )
    _emit_turn_debug = partial(emit_responses_turn_debug, self, mode_decision)

    while True:
        current_input = completed_tool_checkpoint.apply(current_input)
        explicit_context_input = completed_tool_checkpoint.apply(explicit_context_input)
        item_tool_runner = ResponsesItemLevelToolRunner(self, run_tools=run_tools) if use_item_level_mode else None

        _close_item_tool_runner = partial(
            close_responses_item_tool_runner, item_tool_runner
        )
        _abort_item_tool_runner = partial(
            abort_responses_item_tool_runner, item_tool_runner
        )

        stream_text.reset()
        thinking_text.reset()
        request_index += 1
        turn_context = build_responses_turn_context(
            self,
            current_input=current_input,
            tools_payload=tools_payload,
            mode_decision=mode_decision,
            request_index=request_index,
            model_reference_context_item=model_reference_context_item,
            persistent_reference_context_item=persistent_reference_context_item,
            environment_context_builder=build_responses_agent_environment_context,
        )
        context_item = turn_context.context_item
        context_update = turn_context.context_update
        model_reference_context_item = persistent_reference_context_item = context_item
        self._emit_responses_context_update(context_update)
        input_with_context_history = list(current_input)
        if (
            context_history_items
            and turn_context.persistent_update_mode == "unchanged"
            and not runtime_context_history_items(input_with_context_history)
        ):
            input_with_context_history = [*context_history_items, *input_with_context_history]
        request_input = self._with_agent_environment_context(
            input_with_context_history,
            context=turn_context.environment_context,
            project_instructions_context=turn_context.project_instructions_context,
            project_instructions_notice=turn_context.project_instructions_notice,
            turn_context_update=context_update,
            include_runtime_context=True,
        )
        request_input, request_instructions = self._prepare_responses_request_input(request_input)
        if request_instructions:
            sticky_request_instructions = request_instructions
        elif sticky_request_instructions:
            request_instructions = sticky_request_instructions
        if request_index == 1:
            explicit_context_input = list(request_input)
        context_history_items_to_save = runtime_context_history_items(request_input)
        request_payload = build_and_emit_responses_request_payload(
            self,
            request_index=request_index,
            request_input=request_input,
            tools_payload=tools_payload,
            use_stream=use_stream,
            mode_decision=mode_decision,
            context_update=context_update,
            request_instructions=request_instructions,
            provider_options=provider_options,
        )
        payload_json = request_payload.payload_json
        last_request_summary = request_payload.request_summary
        request_input_item_count = request_payload.input_item_count
        try:
            result = self._send_responses_request(
                url=url,
                headers=headers,
                payload_json=payload_json,
                stream_handler=stream_callbacks.on_stream if use_stream else None,
                thinking_stream_handler=stream_callbacks.on_thinking if use_stream else None,
                item_event_handler=item_tool_runner.handle_event if item_tool_runner is not None else None,
            )
        except CancellationRequested as exc:
            _abort_item_tool_runner("cancelled", exc)
            raise
        except RuntimeError as exc:
            _abort_item_tool_runner("stream_failed", exc)
            if self._replace_recent_tool_result_with_submission_error(str(exc)):
                current_input = self._build_responses_input(self._get_messages_with_memory())
                explicit_context_input = list(current_input)
                continue
            raise
        except Exception as exc:
            _abort_item_tool_runner("stream_failed", exc)
            raise

        self._emit_provider_request_completed(last_request_summary, result)
        self._emit_responses_service_tier_result(result)
        content, function_calls, response_id = self._parse_responses_output_envelopes(result)
        turn_structured_result = self._parse_responses_structured_result(result)
        structured_result = structured_result_accumulator.add(turn_structured_result)
        self._last_responses_structured_result = dict(structured_result)
        save_agent_turn_context_reference(self, context_item)
        save_agent_context_history(self, context_history_items_to_save)
        empty_message_action = empty_message_feedback.inspect(
            result=result,
            content=content,
            function_calls=function_calls,
            stream_text=stream_text.text,
            current_input=current_input,
            explicit_context_input=explicit_context_input,
            response_id=response_id,
            request_summary=last_request_summary,
        )
        if empty_message_action.kind != "none":
            if self._tool_context_compaction_gate_active_now():
                self._retry_tool_context_compaction_gate(
                    "the model returned an empty response instead of calling compact_tool_context"
                )
                tools_payload = self._build_responses_tools(
                    self._tool_context_compaction_active_tools(active_tools),
                    web_search_mode,
                )
                current_input = self._build_responses_input(self._get_messages_with_memory())
                explicit_context_input = list(current_input)
                empty_message_feedback.reset()
                _emit_turn_debug(
                    response_id=response_id,
                    content="",
                    function_call_count=0,
                    next_continuation_mode="tool_context_compaction_empty_retry",
                    request_input_item_count=request_input_item_count,
                    followup_item_count=0,
                    stream=use_stream,
                )
                _close_item_tool_runner()
                continue
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
                _close_item_tool_runner()
                return empty_message_action.error_text
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
            _close_item_tool_runner()
            continue

        if function_calls:
            empty_message_feedback.reset()
            display_tool_calls = [to_openai_tool_call(call) for call in function_calls]
            if self._has_visible_text(content):
                self.AssistantProgress(content, tool_calls=display_tool_calls, **turn_structured_result)
            else:
                self.ProviderTurnMetadata(tool_calls=display_tool_calls, **turn_structured_result)
            self.Message("assistant", None, persist=False, tool_calls=display_tool_calls)
            if not run_tools:
                _emit_turn_debug(
                    response_id=response_id,
                    content=content,
                    function_call_count=len(function_calls),
                    next_continuation_mode="function_call_returned",
                    request_input_item_count=request_input_item_count,
                    followup_item_count=0,
                    stream=use_stream,
                )
                _close_item_tool_runner()
                return {
                    "type": "function_call",
                    "function": display_tool_calls[0]["function"],
                    "tool_calls": display_tool_calls,
                }

            continuation_items = self._responses_continuation_input_items(result, function_calls)
            if item_tool_runner is not None:
                executions = item_tool_runner.wait_for_executions(function_calls)
            else:
                executions = execute_tool_call_items_parallel(
                    tool_call_items=function_calls,
                    execute_tool_call_envelopes=self._execute_tool_call_envelopes_parallel,
                )
            self._emit_responses_tool_results_ready(
                response_id=response_id,
                function_call_count=len(function_calls),
                execution_count=len(executions),
                stream=use_stream,
            )
            followup_items = self._build_responses_followup_items(executions)
            _close_item_tool_runner()

            checkpoint_items = checkpoint_completed_tool_context(
                self,
                completed_tool_checkpoint,
                items=explicit_context_input,
                function_calls=function_calls,
                executions=executions,
            )
            if checkpoint_items is not None:
                explicit_context_input = checkpoint_items
                current_input = list(explicit_context_input)

            compaction_changed = bool(getattr(self, "_tool_context_compaction_changed", False))
            compaction_completed = self._tool_context_compaction_gate_completed(executions)
            self._notify_companion_about_failed_tool_executions(executions)

            if compaction_completed and compaction_changed:
                mid_turn_user_messages = consume_mid_turn_user_messages(self)
                for message in mid_turn_user_messages:
                    self.Message("user", message.get("content"), persist=False)
                current_input = self._build_responses_input(self._get_messages_with_memory())
                explicit_context_input = list(current_input)
                tools_payload = self._build_responses_tools(regular_active_tools, web_search_mode)
                _emit_turn_debug(
                    response_id=response_id,
                    content=content,
                    function_call_count=len(function_calls),
                    next_continuation_mode="tool_context_compaction",
                    request_input_item_count=request_input_item_count,
                    followup_item_count=len(followup_items),
                    stream=use_stream,
                )
                continue

            if self._tool_context_compaction_gate_active_now() and any(
                self._execution_tool_name(execution) == "compact_tool_context"
                for execution in executions
            ):
                self._retry_tool_context_compaction_gate("the compaction tool did not produce a context change")

            if not followup_items or (self._responses_requires_response_id_for_tool_followup() and not response_id):
                _emit_turn_debug(
                    response_id=response_id,
                    content=content,
                    function_call_count=len(function_calls),
                    next_continuation_mode="invalid_no_followup",
                    request_input_item_count=request_input_item_count,
                    followup_item_count=0,
                    stream=use_stream,
                )
                return content or "Error: invalid function call continuation in Responses API."

            gate_started = self._run_tool_context_compaction_gate_if_needed(executions)
            if self._tool_context_compaction_gate_active_now():
                tools_payload = self._build_responses_tools(
                    self._tool_context_compaction_active_tools(active_tools),
                    web_search_mode,
                )
            else:
                tools_payload = self._build_responses_tools(regular_active_tools, web_search_mode)

            if gate_started or self._tool_context_compaction_gate_active_now():
                current_input = self._build_responses_input(self._get_messages_with_memory())
                explicit_context_input = list(current_input)
                _emit_turn_debug(
                    response_id=response_id,
                    content=content,
                    function_call_count=len(function_calls),
                    next_continuation_mode="tool_context_compaction_gate",
                    request_input_item_count=request_input_item_count,
                    followup_item_count=len(followup_items),
                    stream=use_stream,
                )
                continue

            mid_turn_user_items = consume_responses_mid_turn_input_items(self)
            explicit_context_input = explicit_context_input + continuation_items + followup_items + mid_turn_user_items
            current_input = list(explicit_context_input)
            _emit_turn_debug(
                response_id=response_id,
                content=content,
                function_call_count=len(function_calls),
                next_continuation_mode="explicit_context",
                request_input_item_count=request_input_item_count,
                followup_item_count=len(followup_items),
                stream=use_stream,
            )
            continue

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
                explicit_context_input = list(current_input)
                _emit_turn_debug(
                    response_id=response_id,
                    content=final_text,
                    function_call_count=0,
                    next_continuation_mode="tool_context_compaction_retry",
                    request_input_item_count=request_input_item_count,
                    followup_item_count=0,
                    stream=use_stream,
                )
                _close_item_tool_runner()
                continue

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
        if content or (use_stream and stream_text.text):
            empty_message_feedback.reset()
        _close_item_tool_runner()
        return finish_responses_message(
            self,
            content=content,
            stream_text=stream_text.text if use_stream else "",
            structured_result=structured_result,
            raw_result=result,
        )
