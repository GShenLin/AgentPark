import json

from src.base_agent import BaseAgent
from src.providers.doubao_http_transport import DoubaoHttpTransport
from src.providers.doubao_image_generation import DoubaoImageGeneration
from src.providers.doubao_responses_mapping import DoubaoResponsesMapping
from src.providers.doubao_responses_runtime import DoubaoResponsesRuntime
from src.providers.doubao_stream_runtime import DoubaoStreamRuntime
from src.providers.tool_feedback import ToolFeedbackMixin
from src.providers.doubao_tool_runtime import DoubaoToolRuntime
from src.providers.doubao_video_generation import DoubaoVideoGeneration
from src.providers.mid_turn_user_inputs import append_mid_turn_user_messages
from src.providers.wan_animate_mix_runtime import WanAnimateMixRuntime
from src.service_host import ServiceHost
from src.switch_utils import parse_switch_mode


class DouBaoAgent(ToolFeedbackMixin, ServiceHost, BaseAgent):
    def __init__(self, provider_id="doubao", memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
        super().__init__(
            provider_id,
            memory_file_path=memory_file_path,
            system_prompt=system_prompt,
            internal_memory_enabled=internal_memory_enabled,
        )
        self.config = self._read_provider_config_from_file()
        self.system_prompt = system_prompt
        self._service_targets_cache = None

    def _iter_service_targets(self) -> tuple[object, ...]:
        try:
            cached = object.__getattribute__(self, "_service_targets_cache")
        except AttributeError:
            cached = None
        if cached is None:
            cached = (
                DoubaoToolRuntime(self),
                DoubaoResponsesMapping(self),
                DoubaoHttpTransport(self),
                DoubaoStreamRuntime(self),
                DoubaoResponsesRuntime(self),
                DoubaoImageGeneration(self),
                DoubaoVideoGeneration(self),
                WanAnimateMixRuntime(self),
            )
            object.__setattr__(self, "_service_targets_cache", cached)
        return cached

    @staticmethod
    def _extract_latest_user_text_prompt(messages) -> str:
        if not isinstance(messages, list):
            return ""
        for msg in reversed(messages):
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(str(part.get("text") or ""))
                return " ".join(part for part in parts if part).strip()
        return ""

    @staticmethod
    def _extract_latest_user_video_content(messages):
        if not isinstance(messages, list):
            return []
        for msg in reversed(messages):
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                text = content.strip()
                return [{"type": "text", "text": text}] if text else []
            if isinstance(content, list):
                normalized = [dict(item) for item in content if isinstance(item, dict)]
                if normalized:
                    return normalized
        return []

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
        if mode == "video_generation":
            content = self._extract_latest_user_video_content(self.messages)
            if not content:
                return "Error: No content found for video generation."

            try:
                tools_payload = [{"type": "web_search"}] if parse_switch_mode(web_search, default="disabled") == "enabled" else None
                return self.generate_video(content, tools=tools_payload)
            except Exception as e:
                return f"Video generation failed: {str(e)}"

        if mode == "image_generation":
            prompt = self._extract_latest_user_text_prompt(self.messages)
            if not prompt:
                return "Error: No prompt found for image generation."

            try:
                result = self.generate_image(prompt)
                paths = []
                if isinstance(result, str):
                    paths = [result]
                elif isinstance(result, list):
                    paths = result

                if paths:
                    for path in paths:
                        self._inject_image_message(path)
                    return f"Image generated successfully: {', '.join(paths)}"

                return str(result)
            except Exception as e:
                return f"Image generation failed: {str(e)}"

        messages = self._restore_recent_tool_results(self._get_messages_with_memory())
        if isinstance(self.system_prompt, str) and self.system_prompt.strip():
            has_system = any((msg or {}).get("role") == "system" for msg in messages)
            if not has_system:
                messages = [{"role": "system", "content": self.system_prompt.strip()}] + messages
        messages = self._compact_tool_result_messages_for_submission(messages)

        active_tools = tools if tools else (self.tool_declarations if self.tool_declarations else None)
        web_search_mode = parse_switch_mode(web_search, default="disabled")
        thinking_mode = parse_switch_mode(thinking, default=None)
        effort_source = reasoning_effort
        if effort_source is None or effort_source == "":
            effort_source = self.config.get("reasoningEffort", "")
        if self._supports_responses_api():
            response_text = self._send_via_responses(
                messages=messages,
                active_tools=active_tools,
                run_tools=run_tools,
                thinking_mode=thinking_mode,
                reasoning_effort=effort_source,
                web_search_mode=web_search_mode,
                stream_handler=stream_handler if stream and callable(stream_handler) else None,
                thinking_stream_handler=thinking_stream_handler if stream and callable(thinking_stream_handler) else None,
            )
            return response_text
        if web_search_mode == "enabled":
            self._require_responses_api("web_search")

        payload = {
            "model": self.config["model"],
            "messages": messages,
        }
        if active_tools:
            payload["tools"] = active_tools
        if thinking_mode in {"enabled", "disabled", "auto"}:
            payload["thinking"] = {"type": thinking_mode}
        if stream:
            payload["stream"] = True

        self._emit_provider_payload_request_summary(payload, request_api="chat_completions", stream=bool(stream))

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['apiKey']}",
        }
        base_url = self.config["baseUrl"].rstrip("/")
        url = f"{base_url}/chat/completions"
        payload_json = json.dumps(payload, ensure_ascii=False)
        max_retries = int(self.config.get("maxRetries", 3))
        retry_delay = float(self.config.get("retryDelaySec", 1))

        try:
            if stream:
                result = self._stream_chat_completions_with_retry(
                    endpoint="chat/completions",
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                    stream_handler=stream_handler if callable(stream_handler) else None,
                    thinking_stream_handler=thinking_stream_handler if callable(thinking_stream_handler) else None,
                )
            else:
                result = self._post_json_with_retry(
                    endpoint="chat/completions",
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                )
        except Exception as e:
            error_text = str(e)
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
            return str(e)

        if "choices" in result and len(result["choices"]) > 0:
            message, selected_idx = self._pick_response_message(result.get("choices"), run_tools)
            if not isinstance(message, dict):
                return f"Error: Invalid message format in choice[{selected_idx}]"
            message = self._normalize_message_tool_calls(message)

            tool_calls = self._extract_tool_calls(message)
            if tool_calls:
                self.Message("assistant", message.get("content"), tool_calls=tool_calls)
                if run_tools:
                    executions = self._execute_tool_calls_parallel(tool_calls)
                    image_messages = self._append_tool_execution_messages_then_warnings(executions)
                    for image_data in image_messages:
                        self._inject_image_message(
                            image_data.get("path"),
                            base64_data=image_data.get("base64"),
                            mime_type=image_data.get("mime_type", "image/png"),
                        )

                    if self._tool_context_compaction_gate_completed(executions):
                        return json.dumps({"status": "tool_context_compaction_completed"}, ensure_ascii=False)
                    self._notify_companion_about_failed_tool_executions(executions)
                    self._run_tool_context_compaction_gate_if_needed(executions)
                    append_mid_turn_user_messages(self)
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

            content = message["content"]
            self.Message("assistant", content)
            return content

        return f"Error: Unexpected response format: {json.dumps(result, ensure_ascii=False)}"
