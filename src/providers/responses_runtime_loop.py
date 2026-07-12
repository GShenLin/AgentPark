import json
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
from src.providers.responses_item_runtime import ResponsesItemLevelToolRunner
from src.providers.responses_runtime_request import build_and_emit_responses_request_payload
from src.providers.responses_runtime_mode import resolve_responses_runtime_mode
from src.providers.responses_runtime_protocol import ResponsesStreamText
from src.providers.tool_call_execution import execute_tool_call_items_parallel
from src.runtime_cancellation import CancellationRequested
from src.tool.tool_call_protocol import to_openai_tool_call

def send_via_responses(
    runtime,
    *,
    messages,
    active_tools,
    run_tools,
    web_search_mode="disabled",
    stream_handler=None,
    thinking_stream_handler=None,
    **provider_options,
):
    self = runtime
    url, headers = self._responses_request_target()
    tools_payload = self._build_responses_tools(active_tools, web_search_mode)
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
    if callable(reset_loop_guard := getattr(self, "_reset_tool_call_loop_guard", None)):
        reset_loop_guard()
    last_request_summary: dict[str, Any] | None = None
    accumulated_structured_result: dict[str, Any] = {}
    self._last_responses_structured_result = {}

    def _accumulate_structured_result(value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            return dict(accumulated_structured_result)
        for key, identity_key in (("server_tool_calls", "call_id"), ("citations", "url")):
            incoming = value.get(key)
            if not isinstance(incoming, list):
                continue
            merged = accumulated_structured_result.setdefault(key, [])
            positions = {
                str(item.get(identity_key) or "").strip(): index
                for index, item in enumerate(merged)
                if isinstance(item, dict) and str(item.get(identity_key) or "").strip()
            }
            for item in incoming:
                if not isinstance(item, dict):
                    continue
                identity = str(item.get(identity_key) or "").strip()
                if identity and identity in positions:
                    merged[positions[identity]] = dict(item)
                else:
                    if identity:
                        positions[identity] = len(merged)
                    merged.append(dict(item))
        response_metadata = value.get("response_metadata")
        if isinstance(response_metadata, dict) and response_metadata:
            accumulated_structured_result["response_metadata"] = dict(response_metadata)
        return {
            key: (list(items) if isinstance(items, list) else dict(items))
            for key, items in accumulated_structured_result.items()
            if items
        }

    def _consume_mid_turn_user_input_items() -> list[dict[str, Any]]:
        messages = consume_mid_turn_user_messages(self)
        items = self._build_responses_input(messages)
        if items:
            self._emit_responses_notice(
                stage="openai_responses_mid_turn_user_input",
                payload={
                    "message_count": len(messages),
                    "input_item_count": len(items),
                },
            )
        return items

    _on_stream = lambda delta_text, full_text: self._emit_stream_text(
        stream_handler, delta_text, stream_text.update(delta_text, full_text)
    )
    thinking_text = ResponsesStreamText()

    def _on_thinking(delta_text, full_text, provider=""):
        if not callable(thinking_stream_handler):
            return
        resolved_full = thinking_text.update(delta_text, full_text)
        thinking_stream_handler(delta_text, resolved_full, provider)

    def _emit_turn_debug(**kwargs):
        self._emit_responses_turn_debug(
            **kwargs,
            responses_mode=mode_decision.mode,
            requested_responses_mode=mode_decision.requested_mode,
            responses_mode_fallback_reason=mode_decision.fallback_reason,
        )

    while True:
        item_tool_runner = ResponsesItemLevelToolRunner(self, run_tools=run_tools) if use_item_level_mode else None

        def _close_item_tool_runner() -> None:
            if item_tool_runner is not None:
                item_tool_runner.close()

        def _abort_item_tool_runner(reason: str, error: Exception) -> None:
            if item_tool_runner is not None:
                item_tool_runner.abort(reason=reason, error=f"{type(error).__name__}: {error}")

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
                stream_handler=_on_stream if use_stream else None,
                thinking_stream_handler=_on_thinking if use_stream else None,
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
        content, function_calls, response_id = self._parse_responses_output_envelopes(result)
        structured_result = _accumulate_structured_result(self._parse_responses_structured_result(result))
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
            gate_active = bool(getattr(self, "_tool_context_compaction_gate_active", False))
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
            if gate_active and empty_message_action.feedback_item is not None:
                # Inside the compaction gate the model must still be forced
                # to call compact_tool_context.  Append the EmptyMessage
                # feedback as an extra user item on top of the existing
                # gate input (which still contains the mandatory gate
                # system prompt), instead of replacing current_input with
                # the lone feedback item (which would discard the gate
                # instruction and guarantee a second refusal).
                current_input = list(current_input) + [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": empty_message_action.feedback_item["content"][0]["text"],
                            }
                        ],
                    }
                ]
            else:
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
            self.AssistantProgress(content, tool_calls=display_tool_calls, **structured_result)
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

            if self._tool_context_compaction_gate_completed(executions):
                _emit_turn_debug(
                    response_id=response_id,
                    content=content,
                    function_call_count=len(function_calls),
                    next_continuation_mode="tool_context_compaction_completed",
                    request_input_item_count=request_input_item_count,
                    followup_item_count=len(followup_items),
                    stream=use_stream,
                )
                return json.dumps({"status": "tool_context_compaction_completed"}, ensure_ascii=False)
            self._notify_companion_about_failed_tool_executions(executions)

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

            self._run_tool_context_compaction_gate_if_needed(executions)
            if self._tool_context_compaction_changed_last_run():
                _emit_turn_debug(
                    response_id=response_id,
                    content=content,
                    function_call_count=len(function_calls),
                    next_continuation_mode="tool_context_compaction",
                    request_input_item_count=request_input_item_count,
                    followup_item_count=len(followup_items),
                    stream=use_stream,
                )
                current_input = self._build_responses_input(self._get_messages_with_memory())
                explicit_context_input = list(current_input)
                continue

            mid_turn_user_items = _consume_mid_turn_user_input_items()
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
        if content:
            empty_message_feedback.reset()
            self.Message("assistant", content, **structured_result)
            _close_item_tool_runner()
            public_result = {
                key: value
                for key, value in structured_result.items()
                if key in {"server_tool_calls", "citations"} and value
            }
            return {"response": content, **public_result} if public_result else content
        if use_stream and stream_text.text:
            empty_message_feedback.reset()
            self.Message("assistant", stream_text.text, **structured_result)
            _close_item_tool_runner()
            public_result = {
                key: value
                for key, value in structured_result.items()
                if key in {"server_tool_calls", "citations"} and value
            }
            return {"response": stream_text.text, **public_result} if public_result else stream_text.text
        self.Message("assistant", content)
        _close_item_tool_runner()
        return json.dumps(result, ensure_ascii=False)

