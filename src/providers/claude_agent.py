from __future__ import annotations

import json

from src.base_agent import BaseAgent
from src.providers.claude_stream_runtime import ClaudeStreamRuntime
from src.providers.claude_chat_runtime import ClaudeChatRuntime
from src.providers.tool_feedback import ToolFeedbackMixin
from src.service_host import ServiceHost
from src.switch_utils import parse_switch_mode


class ClaudeAgent(ToolFeedbackMixin, ServiceHost, BaseAgent):
    def __init__(self, provider_id="claude", memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
        super().__init__(
            provider_id,
            memory_file_path=memory_file_path,
            system_prompt=system_prompt,
            internal_memory_enabled=internal_memory_enabled,
        )
        self.config = self._read_provider_config_from_file()
        self.system_prompt = system_prompt
        self._service_targets_cache = None
        self._reset_tool_call_loop_guard()

    def _iter_service_targets(self) -> tuple[object, ...]:
        try:
            cached = object.__getattribute__(self, "_service_targets_cache")
        except AttributeError:
            cached = None
        if cached is None:
            cached = (ClaudeChatRuntime(self), ClaudeStreamRuntime(self))
            object.__setattr__(self, "_service_targets_cache", cached)
        return cached

    def Send(
        self,
        tools=None,
        run_tools=True,
        mode="chat",
        web_search=None,
        thinking=None,
        reasoning_effort=None,
        stream=False,
        stream_handler=None,
        thinking_stream_handler=None,
        _tool_submission_error_recovered=False,
    ):
        self.config = self._read_provider_config_from_file()
        if str(mode or "chat").strip().lower() != "chat":
            raise ValueError("Claude provider currently supports chat mode only.")
        web_search_mode = parse_switch_mode(web_search, default="disabled", allow_auto=False)
        thinking_mode = parse_switch_mode(thinking, default="disabled")
        effort_source = reasoning_effort
        if effort_source is None or effort_source == "":
            effort_source = self.config.get("reasoningEffort", "")

        messages = self._restore_recent_tool_results(self._get_messages_with_memory())
        if isinstance(self.system_prompt, str) and self.system_prompt.strip():
            has_system = any((msg or {}).get("role") == "system" for msg in messages)
            if not has_system:
                messages = [{"role": "system", "content": self.system_prompt.strip()}] + messages
        messages = self._compact_tool_result_messages_for_submission(messages)

        active_tools = tools if tools else (self.tool_declarations if self.tool_declarations else None)
        if active_tools:
            active_tools = self.to_claude_tool_declarations(active_tools)
        payload = self.build_claude_messages_payload(
            messages=messages,
            tools=active_tools,
            web_search_mode=web_search_mode,
            thinking_mode=thinking_mode,
            reasoning_effort=effort_source,
        )
        self._emit_provider_payload_request_summary(payload, request_api="claude_messages", stream=bool(stream))

        try:
            result = self.send_messages(
                payload,
                stream=stream,
                stream_handler=stream_handler,
                thinking_stream_handler=thinking_stream_handler,
            )
        except Exception as exc:
            error_text = str(exc)
            if (
                not _tool_submission_error_recovered
                and self._replace_recent_tool_result_with_submission_error(error_text)
            ):
                return self.Send(
                    tools=tools,
                    run_tools=run_tools,
                    mode=mode,
                    web_search=web_search_mode,
                    thinking=thinking_mode,
                    reasoning_effort=reasoning_effort,
                    stream=stream,
                    stream_handler=stream_handler,
                    thinking_stream_handler=thinking_stream_handler,
                    _tool_submission_error_recovered=True,
                )
            raise

        message, selected_idx = self.pick_response_message(result.get("choices"), run_tools)
        if not isinstance(message, dict):
            return f"Error: Invalid message format in choice[{selected_idx}]"

        tool_calls = self.extract_tool_calls(message)
        if tool_calls:
            preamble_content = message.get("content")
            preamble_text = preamble_content if isinstance(preamble_content, str) else ""
            # When the request was not streamed (or no stream_handler was
            # supplied), any leading "thinking out loud" text that Claude
            # emitted alongside the tool_calls was never forwarded to the
            # live display -- it only ever reached long-term memory via
            # self.Message() below. Emit it once here so live output shows
            # the same preamble text non-streaming turns already recorded.
            # In the true-streaming path this text was already emitted
            # incrementally as deltas while the SSE response was still in
            # flight, so emitting it again here would duplicate it; guard
            # on `stream` to keep streamed and non-streamed turns each
            # emitting the preamble exactly once.
            if not stream and callable(stream_handler) and preamble_text.strip():
                stream_handler(preamble_text, preamble_text)
            native_blocks = message.get("_claude_content_blocks")
            extra = {"tool_calls": tool_calls}
            if isinstance(native_blocks, list):
                extra["_claude_content_blocks"] = native_blocks
            self.Message("assistant", message.get("content"), **extra)
            if run_tools:
                executions = self.execute_tool_calls_parallel(tool_calls)
                for execution in executions:
                    self.Message(
                        "tool",
                        execution.cleaned_result,
                        tool_call_id=execution.call_id,
                        name=execution.func_name,
                    )
                    warning = self._build_non_retryable_tool_warning(execution.func_name, execution.cleaned_result)
                    if warning:
                        self.Message("system", warning)
                return self.Send(
                    tools=tools,
                    run_tools=run_tools,
                    mode=mode,
                    web_search=web_search_mode,
                    thinking=thinking_mode,
                    reasoning_effort=reasoning_effort,
                    stream=stream,
                    stream_handler=stream_handler,
                    thinking_stream_handler=thinking_stream_handler,
                )
            return {"type": "function_call", "function": tool_calls[0]["function"], "tool_calls": tool_calls}

        content = message.get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        native_blocks = message.get("_claude_content_blocks")
        if isinstance(native_blocks, list):
            self.Message("assistant", text, _claude_content_blocks=native_blocks)
        else:
            self.Message("assistant", text)
        # In the true-streaming path `text` is the already-accumulated
        # full_text from the SSE delta loop (see ClaudeStreamRuntime), so it
        # was already emitted incrementally while the request was in
        # flight. Re-emitting it here as a single "delta" would duplicate
        # the entire message in live output. Only emit here for the
        # non-streamed path, mirroring the tool_calls preamble handling
        # above so the unified stream_handler(delta, full_text) contract
        # is honored exactly once per turn regardless of provider or mode.
        if not stream and callable(stream_handler) and text:
            stream_handler(text, text)
        return text
