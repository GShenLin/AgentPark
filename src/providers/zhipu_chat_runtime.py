import json

from src.providers.tool_call_execution import execute_tool_call_items_parallel
from src.providers.tool_call_execution import parse_openai_tool_call_items
from src.providers.mid_turn_user_inputs import append_mid_turn_user_messages
from src.providers.zhipu_http_transport import ZhipuHttpTransport
from src.switch_utils import require_bool_switch
from src.tool.tool_call_protocol import to_openai_tool_call


class ZhipuChatRuntime(ZhipuHttpTransport):
    def _build_payload(self, *, messages, active_tools, reasoning_effort, thinking_mode, stream: bool) -> dict:
        payload = {
            "model": self.config["model"],
            "messages": messages,
        }
        if active_tools:
            payload["tools"] = active_tools
        if stream:
            payload["stream"] = True
        if reasoning_effort:
            payload["reasoning_effort"] = str(reasoning_effort)
        if thinking_mode in {"enabled", "disabled"}:
            payload["thinking"] = {"type": thinking_mode}

        clear_thinking = self.config.get("clearThinking")
        if clear_thinking is not None:
            thinking = payload.get("thinking")
            if not isinstance(thinking, dict):
                thinking = {}
                payload["thinking"] = thinking
            thinking["clear_thinking"] = require_bool_switch(clear_thinking, "thinking.clear_thinking", prefix="Zhipu")

        max_tokens = self.config.get("maxTokens")
        if max_tokens not in {None, ""}:
            if not isinstance(max_tokens, int) or isinstance(max_tokens, bool):
                raise ValueError("Zhipu maxTokens must be an integer.")
            payload["max_tokens"] = max_tokens
        for key in ("temperature", "top_p", "stop"):
            if self.config.get(key) is not None:
                payload[key] = self.config.get(key)
        self._apply_optional_documented_fields(payload)
        return payload

    def _apply_optional_documented_fields(self, payload: dict) -> None:
        bool_fields = (
            ("do_sample", "doSample"),
            ("tool_stream", "toolStream"),
        )
        for field_name, key in bool_fields:
            value = self.config.get(key)
            if value is not None:
                payload[field_name] = require_bool_switch(value, field_name, prefix="Zhipu")

        passthrough_fields = (
            ("response_format", "responseFormat"),
            ("tool_choice", "toolChoice"),
            ("request_id", "requestId"),
            ("user_id", "userId"),
        )
        for field_name, key in passthrough_fields:
            value = self.config.get(key)
            if value is not None:
                payload[field_name] = value

    @staticmethod
    def _pick_response_message(result):
        choices = result.get("choices") if isinstance(result, dict) else None
        if not isinstance(choices, list) or not choices:
            return None, ""
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message")
        return message if isinstance(message, dict) else None, str(choice.get("finish_reason") or "")

    def _send_chat_completions(self, *, messages, active_tools, run_tools, reasoning_effort, thinking_mode, stream, stream_handler):
        url = self._chat_completions_url()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['apiKey']}",
        }
        payload = self._build_payload(
            messages=messages,
            active_tools=active_tools,
            reasoning_effort=reasoning_effort,
            thinking_mode=thinking_mode,
            stream=bool(stream),
        )
        self._emit_provider_payload_request_summary(payload, request_api="chat_completions", stream=bool(stream))
        payload_json = json.dumps(payload, ensure_ascii=False)
        if stream:
            result = self._stream_chat_completions_with_retry(
                endpoint="chat/completions",
                url=url,
                headers=headers,
                payload_json=payload_json,
                stream_handler=stream_handler if callable(stream_handler) else None,
            )
        else:
            result = self._post_json_with_retry(
                endpoint="chat/completions",
                url=url,
                headers=headers,
                payload_json=payload_json,
            )

        message, finish_reason = self._pick_response_message(result)
        if not isinstance(message, dict):
            if finish_reason == "model_context_window_exceeded":
                return "Error: Zhipu model context window exceeded."
            return json.dumps(result, ensure_ascii=False)

        tool_call_items = parse_openai_tool_call_items(message.get("tool_calls"), provider="zhipu_chat")
        if tool_call_items:
            display_tool_calls = [to_openai_tool_call(item) for item in tool_call_items]
            self.Message("assistant", message.get("content") or "", tool_calls=display_tool_calls)
            if not run_tools:
                return {
                    "type": "function_call",
                    "function": display_tool_calls[0]["function"],
                    "tool_calls": display_tool_calls,
                }
            executions = execute_tool_call_items_parallel(
                tool_call_items=tool_call_items,
                execute_tool_call_envelopes=self._execute_tool_call_envelopes_parallel,
            )
            self._append_tool_execution_messages_then_warnings(executions)
            if self._tool_context_compaction_gate_completed(executions):
                return json.dumps({"status": "tool_context_compaction_completed"}, ensure_ascii=False)
            self._notify_companion_about_failed_tool_executions(executions)
            self._run_tool_context_compaction_gate_if_needed(executions)
            append_mid_turn_user_messages(self)
            return self.Send(
                run_tools=run_tools,
                mode="chat",
                reasoning_effort=reasoning_effort,
                thinking=thinking_mode,
                stream=stream,
                stream_handler=stream_handler,
            )

        content = message.get("content")
        if finish_reason == "model_context_window_exceeded" and not content:
            content = "Error: Zhipu model context window exceeded."
        self.Message("assistant", "" if content is None else content)
        return "" if content is None else content
