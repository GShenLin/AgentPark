import json
from typing import Any

from src.providers.agent_environment_context import build_agent_environment_context
from src.providers.agent_environment_context import format_agent_environment_context
from src.providers.responses_empty_message import EmptyMessageFeedbackController
from src.providers.responses_followup import build_responses_followup_items
from src.providers.responses_input_items import build_responses_message_input_item
from src.providers.responses_item_runtime import ResponsesItemLevelToolRunner
from src.providers.responses_request_summary import build_responses_request_summary
from src.providers.responses_runtime_mode import resolve_responses_runtime_mode
from src.providers.responses_runtime_protocol import ResponsesStreamText, is_previous_response_missing_error
from src.providers.tool_feedback import ToolFeedbackMixin
from src.providers.tool_call_execution import execute_tool_call_items_parallel
from src.runtime_cancellation import CancellationRequested
from src.service_host import HostBoundService
from src.tool.tool_call_protocol import to_openai_tool_call


class ResponsesRuntime(ToolFeedbackMixin, HostBoundService):
    def _send_via_responses(
        self,
        *,
        messages,
        active_tools,
        run_tools,
        web_search_mode="disabled",
        stream_handler=None,
        **provider_options,
    ):
        url, headers = self._responses_request_target()
        tools_payload = self._build_responses_tools(active_tools, web_search_mode)
        current_input = self._build_responses_input(messages)
        explicit_context_input = list(current_input)
        previous_response_fallback_input = None
        previous_response_id = ""
        continuation_mode = self._responses_continuation_mode()
        stream_text = ResponsesStreamText()
        mode_decision = resolve_responses_runtime_mode(self)
        use_item_level_mode = mode_decision.mode == "item_level"
        use_stream = callable(stream_handler) or use_item_level_mode
        empty_message_feedback = EmptyMessageFeedbackController()
        request_index = 0
        reset_loop_guard = getattr(self, "_reset_tool_call_loop_guard", None)
        if callable(reset_loop_guard):
            reset_loop_guard()
        last_request_summary: dict[str, Any] | None = None

        def _on_stream(delta_text, full_text):
            self._emit_stream_text(stream_handler, delta_text, stream_text.update(delta_text, full_text))

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
            request_previous_response_id = previous_response_id
            request_input = self._with_agent_environment_context(current_input)
            request_input_item_count = len(request_input) if isinstance(request_input, list) else 0
            payload = self._build_responses_payload(
                current_input=request_input,
                previous_response_id=previous_response_id,
                tools_payload=tools_payload,
                use_stream=use_stream,
                provider_options=provider_options,
            )
            payload_json = json.dumps(payload, ensure_ascii=False)
            request_index += 1
            last_request_summary = build_responses_request_summary(
                request_index=request_index,
                continuation_mode=continuation_mode,
                previous_response_id=previous_response_id,
                current_input=request_input,
                tools_payload=tools_payload,
                stream=use_stream,
                responses_mode=mode_decision.mode,
                requested_responses_mode=mode_decision.requested_mode,
            )
            self._emit_responses_request_summary(last_request_summary)
            self._emit_responses_request_start(
                request_index=request_index,
                previous_response_id=previous_response_id,
                input_item_count=request_input_item_count,
                stream=use_stream,
                responses_mode=mode_decision.mode,
                requested_responses_mode=mode_decision.requested_mode,
            )
            try:
                result = self._send_responses_request(
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    stream_handler=_on_stream if use_stream else None,
                    item_event_handler=item_tool_runner.handle_event if item_tool_runner is not None else None,
                )
            except CancellationRequested as exc:
                _abort_item_tool_runner("cancelled", exc)
                raise
            except RuntimeError as exc:
                _abort_item_tool_runner("stream_failed", exc)
                if (
                    previous_response_id
                    and previous_response_fallback_input
                    and is_previous_response_missing_error(exc)
                ):
                    self._emit_responses_previous_response_missing(
                        previous_response_id=previous_response_id,
                        fallback_input_item_count=len(previous_response_fallback_input),
                        stream=use_stream,
                    )
                    previous_response_id = ""
                    current_input = previous_response_fallback_input
                    previous_response_fallback_input = None
                    continue
                if self._replace_recent_tool_result_with_submission_error(str(exc)):
                    current_input = self._build_responses_input(self._get_messages_with_memory())
                    explicit_context_input = list(current_input)
                    previous_response_fallback_input = None
                    previous_response_id = ""
                    continue
                raise
            except Exception as exc:
                _abort_item_tool_runner("stream_failed", exc)
                raise

            content, function_calls, response_id = self._parse_responses_output_envelopes(result)
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
                        request_previous_response_id=request_previous_response_id,
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
                    previous_response_fallback_input = None
                    previous_response_id = ""
                else:
                    previous_response_id = ""
                    current_input = empty_message_action.next_input
                    previous_response_fallback_input = None
                _emit_turn_debug(
                    response_id=response_id,
                    content=empty_message_action.feedback_item["content"][0]["text"],
                    function_call_count=0,
                    next_continuation_mode="empty_message_feedback",
                    request_previous_response_id=request_previous_response_id,
                    request_input_item_count=request_input_item_count,
                    followup_item_count=1,
                    stream=use_stream,
                )
                _close_item_tool_runner()
                continue

            if function_calls:
                empty_message_feedback.reset()
                display_tool_calls = [to_openai_tool_call(call) for call in function_calls]
                self.Message("assistant", content, tool_calls=display_tool_calls)
                self._persist_assistant_tool_call_note_if_available(
                    {"role": "assistant", "content": content, "tool_calls": display_tool_calls}
                )
                if not run_tools:
                    _emit_turn_debug(
                        response_id=response_id,
                        content=content,
                        function_call_count=len(function_calls),
                        next_continuation_mode="function_call_returned",
                        request_previous_response_id=request_previous_response_id,
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

                if self._operational_memory_gate_completed(executions):
                    _emit_turn_debug(
                        response_id=response_id,
                        content=content,
                        function_call_count=len(function_calls),
                        next_continuation_mode="operational_memory_gate_completed",
                        request_previous_response_id=request_previous_response_id,
                        request_input_item_count=request_input_item_count,
                        followup_item_count=len(followup_items),
                        stream=use_stream,
                    )
                    return json.dumps({"status": "memory_gate_completed"}, ensure_ascii=False)
                if self._tool_context_compaction_gate_completed(executions):
                    _emit_turn_debug(
                        response_id=response_id,
                        content=content,
                        function_call_count=len(function_calls),
                        next_continuation_mode="tool_context_compaction_completed",
                        request_previous_response_id=request_previous_response_id,
                        request_input_item_count=request_input_item_count,
                        followup_item_count=len(followup_items),
                        stream=use_stream,
                    )
                    return json.dumps({"status": "tool_context_compaction_completed"}, ensure_ascii=False)
                self._run_operational_memory_gate_for_failed_executions(executions)

                if not followup_items or (self._responses_requires_response_id_for_tool_followup() and not response_id):
                    _emit_turn_debug(
                        response_id=response_id,
                        content=content,
                        function_call_count=len(function_calls),
                        next_continuation_mode="invalid_no_followup",
                        request_previous_response_id=request_previous_response_id,
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
                        request_previous_response_id=request_previous_response_id,
                        request_input_item_count=request_input_item_count,
                        followup_item_count=len(followup_items),
                        stream=use_stream,
                    )
                    current_input = self._build_responses_input(self._get_messages_with_memory())
                    explicit_context_input = list(current_input)
                    previous_response_fallback_input = None
                    previous_response_id = ""
                    continue

                explicit_context_input = explicit_context_input + continuation_items + followup_items
                previous_response_fallback_input = list(explicit_context_input)
                if response_id and continuation_mode == "previous_response_id":
                    previous_response_id = response_id
                    current_input = self._responses_previous_response_input(continuation_items, followup_items)
                    _emit_turn_debug(
                        response_id=response_id,
                        content=content,
                        function_call_count=len(function_calls),
                        next_continuation_mode="previous_response_id",
                        request_previous_response_id=request_previous_response_id,
                        request_input_item_count=request_input_item_count,
                        followup_item_count=len(followup_items),
                        stream=use_stream,
                    )
                else:
                    previous_response_id = ""
                    current_input = list(explicit_context_input)
                    _emit_turn_debug(
                        response_id=response_id,
                        content=content,
                        function_call_count=len(function_calls),
                        next_continuation_mode="explicit_context",
                        request_previous_response_id=request_previous_response_id,
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
                request_previous_response_id=request_previous_response_id,
                request_input_item_count=request_input_item_count,
                followup_item_count=0,
                stream=use_stream,
            )
            if content:
                empty_message_feedback.reset()
                self.Message("assistant", content)
                _close_item_tool_runner()
                return content
            if use_stream and stream_text.text:
                empty_message_feedback.reset()
                self.Message("assistant", stream_text.text)
                _close_item_tool_runner()
                return stream_text.text
            self.Message("assistant", content)
            _close_item_tool_runner()
            return json.dumps(result, ensure_ascii=False)

    def _build_responses_payload(
        self,
        *,
        current_input,
        previous_response_id,
        tools_payload,
        use_stream,
        provider_options,
    ) -> dict[str, Any]:
        payload = {"model": self.config["model"], "input": current_input}
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        if tools_payload:
            payload["tools"] = tools_payload
        payload.update(self._responses_payload_extra(**provider_options))
        if use_stream:
            payload["stream"] = True
        return payload

    def _persist_assistant_tool_call_note_if_available(self, message: dict[str, Any]) -> None:
        callback = getattr(self, "_aitools_persist_assistant_tool_call_note", None)
        if callable(callback):
            callback(message)

    def _with_agent_environment_context(self, current_input: Any) -> list[Any]:
        items = list(current_input) if isinstance(current_input, list) else []
        context = build_agent_environment_context(self, current_input=current_input)
        if not context:
            return items
        text = format_agent_environment_context(context)
        return [
            build_responses_message_input_item(
                role="system",
                content=[{"type": "input_text", "text": text}],
            ),
            *items,
        ]

    def _send_responses_request(self, *, url, headers, payload_json, stream_handler, item_event_handler=None):
        if callable(stream_handler):
            return self._stream_responses_request(
                url=url,
                headers=headers,
                payload_json=payload_json,
                stream_handler=stream_handler,
                item_event_handler=item_event_handler,
            )
        return self._post_responses_request(
            url=url,
            headers=headers,
            payload_json=payload_json,
        )

    def _build_responses_followup_items(self, executions) -> list[dict[str, Any]]:
        return build_responses_followup_items(self, executions)

    def _emit_responses_request_start(
        self,
        *,
        request_index: int,
        previous_response_id: str,
        input_item_count: int,
        stream: bool,
        responses_mode: str,
        requested_responses_mode: str,
    ) -> None:
        emitter = getattr(self, "_emit_provider_runtime_notice", None)
        if not callable(emitter):
            return
        emitter(
            message=json.dumps(
                {
                    "request_index": int(request_index),
                    "previous_response_id": str(previous_response_id or ""),
                    "previous_response_id_present": bool(previous_response_id),
                    "input_item_count": int(input_item_count),
                    "stream": bool(stream),
                    "responses_mode": str(responses_mode or ""),
                    "requested_responses_mode": str(requested_responses_mode or ""),
                },
                ensure_ascii=False,
            ),
            stage="openai_responses_request_start",
        )

    def _emit_responses_tool_results_ready(
        self,
        *,
        response_id: str,
        function_call_count: int,
        execution_count: int,
        stream: bool,
    ) -> None:
        emitter = getattr(self, "_emit_provider_runtime_notice", None)
        if not callable(emitter):
            return
        emitter(
            message=json.dumps(
                {
                    "response_id": str(response_id or ""),
                    "function_call_count": int(function_call_count),
                    "execution_count": int(execution_count),
                    "stream": bool(stream),
                },
                ensure_ascii=False,
            ),
            stage="openai_responses_tool_results_ready",
        )

    def _responses_request_target(self) -> tuple[str, dict[str, str]]:
        base_url = self.config["baseUrl"].rstrip("/")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.config['apiKey']}"}
        return f"{base_url}/responses", headers

    def _responses_payload_extra(self, **_provider_options) -> dict[str, Any]:
        return {}

    def _post_responses_request(self, *, url, headers, payload_json):
        return self._post_json_with_retry(endpoint="responses", url=url, headers=headers, payload_json=payload_json)

    def _stream_responses_request(self, *, url, headers, payload_json, stream_handler, item_event_handler=None):
        return self._stream_responses_with_retry(endpoint="responses", url=url, headers=headers, payload_json=payload_json, stream_handler=stream_handler, item_event_handler=item_event_handler)

    def _responses_continuation_mode(self) -> str:
        return "previous_response_id"

    def _responses_continuation_input_items(self, _result, function_calls):
        return self._build_responses_function_call_input_items(function_calls)

    def _responses_previous_response_input(self, continuation_items, followup_items):
        return list(continuation_items) + list(followup_items)

    def _responses_requires_response_id_for_tool_followup(self) -> bool:
        return False

    def _responses_tool_output(self, execution):
        return self._compact_tool_result_for_submission_if_needed(
            tool_name=execution.func_name,
            call_id=execution.call_id,
            content=execution.cleaned_result,
        )

    def _emit_responses_request_summary(self, summary: dict[str, Any]) -> None:
        emitter = getattr(self, "_emit_provider_runtime_notice", None)
        if not callable(emitter):
            return
        emitter(
            message=json.dumps(summary, ensure_ascii=False, sort_keys=True),
            stage="openai_responses_request_summary",
        )

    def _validate_responses_followup_call_id(self, _call_id: str) -> None:
        return None

    def _emit_responses_item_level_abort(self, _summary: dict[str, Any]) -> None:
        return None

    def _emit_responses_previous_response_missing(
        self,
        *,
        previous_response_id,
        fallback_input_item_count,
        stream,
    ) -> None:
        return None

    def _emit_responses_turn_debug(
        self,
        *,
        response_id,
        content,
        function_call_count,
        next_continuation_mode,
        request_previous_response_id,
        request_input_item_count,
        followup_item_count,
        stream,
        responses_mode="whole_response",
        requested_responses_mode="whole_response",
        responses_mode_fallback_reason="",
    ) -> None:
        return None
