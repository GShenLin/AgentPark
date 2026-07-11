from __future__ import annotations

import json
from typing import Any

from src.providers.agent_collaboration_mode import format_collaboration_mode_instructions
from src.providers.agent_environment_context import build_agent_environment_context
from src.providers.agent_environment_context import format_agent_environment_context
from src.providers.agent_permissions_context import build_agent_permissions_context
from src.providers.agent_permissions_context import format_agent_permissions_context
from src.providers.agent_project_instructions import format_agent_project_instructions_context
from src.providers.agent_runtime_context import get_agent_runtime_context
from src.providers.responses_followup import build_responses_followup_items
from src.providers.responses_input_items import build_responses_message_input_item
from src.providers.responses_runtime_context import has_collaboration_context
from src.providers.responses_runtime_context import has_environment_context
from src.providers.responses_runtime_context import has_permissions_context
from src.providers.responses_runtime_context import has_project_instructions_context
from src.providers.responses_runtime_context import peel_initial_developer_items


class ResponsesRuntimeMethods:
    def _build_responses_payload(
        self,
        *,
        current_input,
        tools_payload,
        use_stream,
        provider_options,
        instructions="",
    ) -> dict[str, Any]:
        payload = {"model": self.config["model"], "input": current_input}
        if str(instructions or "").strip():
            payload["instructions"] = str(instructions).strip()
        if tools_payload:
            payload["tools"] = tools_payload
            payload["tool_choice"] = self._responses_tool_choice()
            payload["parallel_tool_calls"] = self._responses_parallel_tool_calls()
        payload.update(self._responses_payload_extra(**provider_options))
        if use_stream:
            payload["stream"] = True
        return payload

    def _responses_tool_choice(self) -> str:
        text = str(self.config.get("responsesToolChoice") or "").strip()
        return text or "auto"

    def _responses_parallel_tool_calls(self) -> bool:
        value = self.config.get("responsesParallelToolCalls")
        if isinstance(value, bool):
            return value
        if value is None:
            return True
        text = str(value).strip().lower()
        if text == "false":
            return False
        if text == "true":
            return True
        return True

    def _prepare_responses_request_input(self, current_input: Any) -> tuple[list[Any], str]:
        items = list(current_input) if isinstance(current_input, list) else []
        runtime_context = get_agent_runtime_context(self)
        return items, str(runtime_context.responses_instruction or "").strip()

    def _with_agent_environment_context(
        self,
        current_input: Any,
        *,
        context: dict[str, Any] | None = None,
        project_instructions_context: dict[str, Any] | None = None,
        project_instructions_notice: str = "",
        turn_context_update: dict[str, Any] | None = None,
        include_runtime_context: bool = True,
    ) -> list[Any]:
        _ = turn_context_update
        items = list(current_input) if isinstance(current_input, list) else []
        if not include_runtime_context:
            return items
        prefix_items = []
        developer_context_parts = []
        initial_developer_parts, items = peel_initial_developer_items(items)
        initial_developer_item = {
            "type": "message",
            "role": "developer",
            "content": initial_developer_parts,
        }
        if not has_permissions_context(items) and not has_permissions_context([initial_developer_item]):
            developer_context_parts.append(
                {
                    "type": "input_text",
                    "text": format_agent_permissions_context(
                        build_agent_permissions_context(self, context)
                    ),
                }
            )
        collaboration_text = format_collaboration_mode_instructions(
            get_agent_runtime_context(self).collaboration_mode
        )
        if (
            collaboration_text
            and not has_collaboration_context(items)
            and not has_collaboration_context([initial_developer_item])
        ):
            developer_context_parts.append({"type": "input_text", "text": collaboration_text})
        developer_context_parts.extend(initial_developer_parts)
        if developer_context_parts:
            prefix_items.append(
                build_responses_message_input_item(
                    role="developer",
                    content=developer_context_parts,
                )
            )
        contextual_user_parts = []
        if context is None:
            context = build_agent_environment_context(self, current_input=current_input)
        if context and not has_environment_context(items):
            contextual_user_parts.append({"type": "input_text", "text": format_agent_environment_context(context)})
        project_instructions_text = format_agent_project_instructions_context(
            project_instructions_context or {},
            notice=project_instructions_notice,
        )
        if project_instructions_text and not has_project_instructions_context(items):
            contextual_user_parts.append({"type": "input_text", "text": project_instructions_text})
        if contextual_user_parts:
            prefix_items.append(build_responses_message_input_item(role="user", content=contextual_user_parts))
        return [*prefix_items, *items]

    def _send_responses_request(self, *, url, headers, payload_json, stream_handler, thinking_stream_handler=None, item_event_handler=None):
        if callable(stream_handler) or callable(thinking_stream_handler):
            return self._stream_responses_request(
                url=url,
                headers=headers,
                payload_json=payload_json,
                stream_handler=stream_handler,
                thinking_stream_handler=thinking_stream_handler,
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
        input_item_count: int,
        stream: bool,
        responses_mode: str,
        requested_responses_mode: str,
    ) -> None:
        self._emit_responses_notice(
            stage="openai_responses_request_start",
            payload={
                "request_index": int(request_index),
                "input_item_count": int(input_item_count),
                "stream": bool(stream),
                "responses_mode": str(responses_mode or ""),
                "requested_responses_mode": str(requested_responses_mode or ""),
            },
        )

    def _emit_responses_tool_results_ready(
        self,
        *,
        response_id: str,
        function_call_count: int,
        execution_count: int,
        stream: bool,
    ) -> None:
        self._emit_responses_notice(
            stage="openai_responses_tool_results_ready",
            payload={
                "response_id": str(response_id or ""),
                "function_call_count": int(function_call_count),
                "execution_count": int(execution_count),
                "stream": bool(stream),
            },
        )

    def _responses_request_target(self) -> tuple[str, dict[str, str]]:
        from src.provider_auth import resolve_provider_request_credentials

        credentials = resolve_provider_request_credentials(self.config)
        headers = {"Content-Type": "application/json", **credentials.headers}
        return f"{credentials.base_url}/responses", headers

    def _refresh_responses_auth_headers(self, headers: dict[str, str]) -> bool:
        if str(self.config.get("authMode") or "api_key").strip().lower() != "codex":
            return False
        from src.provider_auth import resolve_provider_request_credentials

        credentials = resolve_provider_request_credentials(self.config, force_refresh=True)
        headers.clear()
        headers.update({"Content-Type": "application/json", **credentials.headers})
        return True

    def _responses_payload_extra(self, **_provider_options) -> dict[str, Any]:
        return {}

    def _post_responses_request(self, *, url, headers, payload_json):
        return self._post_json_with_retry(endpoint="responses", url=url, headers=headers, payload_json=payload_json)

    def _stream_responses_request(self, *, url, headers, payload_json, stream_handler, thinking_stream_handler=None, item_event_handler=None):
        return self._stream_responses_with_retry(
            endpoint="responses",
            url=url,
            headers=headers,
            payload_json=payload_json,
            stream_handler=stream_handler,
            thinking_stream_handler=thinking_stream_handler,
            item_event_handler=item_event_handler,
        )

    def _responses_continuation_input_items(self, _result, function_calls):
        return self._build_responses_function_call_input_items(function_calls)

    def _responses_requires_response_id_for_tool_followup(self) -> bool:
        return False

    def _responses_tool_output(self, execution):
        return self._compact_tool_result_for_submission_if_needed(
            tool_name=execution.func_name,
            call_id=execution.call_id,
            content=execution.cleaned_result,
        )

    def _emit_responses_context_update(self, update: dict[str, Any]) -> None:
        self._emit_responses_notice(stage="openai_responses_context_update", payload=update, sort_keys=True)

    def _emit_responses_payload_log(self, payload: dict[str, Any]) -> None:
        self._emit_responses_notice(stage="openai_responses_request_payload_log", payload=payload, sort_keys=True)

    def _emit_responses_notice(self, *, stage: str, payload: dict[str, Any], sort_keys: bool = False) -> None:
        emitter = getattr(self, "_emit_provider_runtime_notice", None)
        if not callable(emitter):
            return
        emitter(
            message=json.dumps(payload, ensure_ascii=False, sort_keys=sort_keys),
            stage=stage,
        )

    def _validate_responses_followup_call_id(self, _call_id: str) -> None:
        return None

    def _emit_responses_item_level_abort(self, _summary: dict[str, Any]) -> None:
        return None

    def _emit_responses_turn_debug(
        self,
        *,
        response_id,
        content,
        function_call_count,
        next_continuation_mode,
        request_input_item_count,
        followup_item_count,
        stream,
        responses_mode="whole_response",
        requested_responses_mode="whole_response",
        responses_mode_fallback_reason="",
    ) -> None:
        return None
