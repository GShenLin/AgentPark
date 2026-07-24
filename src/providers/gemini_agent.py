import json
import random
import time
import urllib.error
import urllib.request

from src.base_agent import BaseAgent
from src.providers.gemini_function_runtime import GeminiFunctionRuntime
from src.providers.gemini_image_generation import GeminiImageGeneration
from src.providers.gemini_message_mapping import attach_gemini_call_ids
from src.providers.gemini_message_mapping import map_messages_to_gemini
from src.providers.gemini_stream_runtime import GeminiStreamRuntime
from src.providers.image_generation_input import latest_image_generation_input
from src.providers.mid_turn_user_inputs import append_mid_turn_user_messages
from src.providers.provider_pressure import acquire_provider_pressure
from src.service_host import ServiceHost


class GeminiAgent(ServiceHost, BaseAgent):
    def __init__(self, provider_id="gemini", memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
        super().__init__(
            provider_id,
            memory_file_path=memory_file_path,
            system_prompt=system_prompt,
            internal_memory_enabled=internal_memory_enabled,
        )
        self.config = self._read_provider_config_from_file()
        self._service_targets_cache = None

    def _iter_service_targets(self) -> tuple[object, ...]:
        try:
            cached = object.__getattribute__(self, "_service_targets_cache")
        except AttributeError:
            cached = None
        if cached is None:
            cached = (
                GeminiFunctionRuntime(self),
                GeminiStreamRuntime(self),
                GeminiImageGeneration(self),
            )
            object.__setattr__(self, "_service_targets_cache", cached)
        return cached

    @staticmethod
    def _extract_latest_user_prompt(messages) -> str:
        if not isinstance(messages, list):
            return ""
        for msg in reversed(messages):
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, dict):
                return str(content.get("text") or "")
        return ""

    def Send(
        self,
        tools=None,
        run_tools=True,
        mode="chat",
        web_search=None,
        thinking=None,
        stream=False,
        stream_handler=None,
        mode_options=None,
    ):
        self.config = self._read_provider_config_from_file()
        _ = web_search
        _ = thinking
        if mode == "image_generation":
            options = dict(mode_options or {}) if isinstance(mode_options, dict) else {}
            prompt, references = latest_image_generation_input(self.messages, options.get("image_references"))
            if not prompt:
                return "Error: No prompt found for image generation."

            try:
                result = self.generate_image(
                    prompt,
                    filename_prefix=options.get("image_filename_prefix") or "generated_image",
                    image=references or None,
                    aspect_ratio=options.get("image_aspect_ratio"),
                    image_size=options.get("image_size"),
                    response_format=options.get("image_response_format"),
                    watermark=options.get("image_watermark"),
                )
                image_value = result.get("image_path") if isinstance(result, dict) else result
                paths = image_value if isinstance(image_value, list) else [image_value]
                normalized = [str(path).strip() for path in paths if str(path or "").strip()]
                return {
                    "response": f"Image generated successfully: {', '.join(normalized)}",
                    "image_path": normalized[0] if len(normalized) == 1 else normalized,
                }
            except Exception as e:
                return f"Image generation failed: {str(e)}"

        messages = self._get_messages_with_memory()
        system_instruction, gemini_contents = map_messages_to_gemini(messages)

        payload = {"contents": gemini_contents}
        if system_instruction:
            payload["system_instruction"] = system_instruction
        if str(mode or "chat").strip().lower() == "imagechat":
            payload["generationConfig"] = {"responseModalities": ["TEXT", "IMAGE"]}

        active_tools = tools if tools else (self.tool_declarations if self.tool_declarations else None)
        compaction_tool_filter = getattr(self, "_tool_context_compaction_active_tools", None)
        if callable(compaction_tool_filter):
            active_tools = compaction_tool_filter(active_tools)
        if active_tools:
            gemini_tools = []
            if isinstance(active_tools, list):
                for tool in active_tools:
                    gemini_tools.append(self._convert_tool_to_gemini(tool))
            payload["tools"] = [{"function_declarations": gemini_tools}]

        base_url = self.config["baseUrl"].rstrip("/")
        model = self.config["model"]
        if stream:
            url = f"{base_url}/models/{model}:streamGenerateContent?alt=sse"
        else:
            url = f"{base_url}/models/{model}:generateContent"

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.config["apiKey"],
        }
        payload_json = json.dumps(payload)

        max_retries = int(self.config.get("maxRetries", 2))
        retry_delay = float(self.config.get("retryDelaySec", 1))
        timeout = self.config.get("timeoutMs", 60000) / 1000

        for attempt in range(max_retries + 1):
            try:
                if stream:
                    result = self._stream_generate_content_once(
                        url=url,
                        headers=headers,
                        payload_json=payload_json,
                        timeout_sec=timeout,
                        stream_handler=stream_handler if callable(stream_handler) else None,
                    )
                else:
                    req = urllib.request.Request(
                        url,
                        data=payload_json.encode("utf-8"),
                        headers=headers,
                        method="POST",
                    )
                    with acquire_provider_pressure(self):
                        with urllib.request.urlopen(req, timeout=timeout) as response:
                            if response.status != 200:
                                return f"Error: {response.status} - {response.read().decode('utf-8')}"
                            response_data = response.read().decode("utf-8")
                            result = json.loads(response_data)

                if "candidates" in result and len(result["candidates"]) > 0:
                    candidate, candidate_idx = self._pick_candidate_content(result.get("candidates"), run_tools)
                    if not isinstance(candidate, dict):
                        return f"Error: Invalid candidate format at index {candidate_idx}"
                    if "content" in candidate and "parts" in candidate["content"]:
                        parts = candidate["content"]["parts"]
                        function_calls, text_content, has_text = self._extract_candidate_calls_and_text(parts)
                        has_function_call = bool(function_calls)

                        if has_function_call:
                            self.AssistantProgress(text_content if has_text else None)
                            envelopes = self._normalize_gemini_function_calls(function_calls)
                            protocol_parts = attach_gemini_call_ids(
                                parts,
                                [envelope.call_id for envelope in envelopes],
                            )
                            self.Message("assistant", None, persist=False, parts=protocol_parts)
                            if run_tools:
                                executions = self._execute_tool_call_envelopes_parallel(envelopes)
                                image_messages = self._append_tool_execution_messages_then_warnings(
                                    executions,
                                    message_role="function",
                                )
                                for image_data in image_messages:
                                    if image_data:
                                        if image_data.get("base64"):
                                            self.Message(
                                                "user",
                                                {
                                                    "type": "image_data",
                                                    "data": image_data["base64"],
                                                    "mime_type": image_data.get("mime_type", "image/png"),
                                                    "text": "Image captured by tool.",
                                                },
                                            )
                                        elif image_data.get("path"):
                                            self.Message(
                                                "user",
                                                {
                                                    "type": "image",
                                                    "path": image_data["path"],
                                                    "text": "I have taken the screenshot. Please analyze it.",
                                                },
                                            )

                                self._tool_context_compaction_gate_completed(executions)
                                self._notify_companion_about_failed_tool_executions(executions)
                                self._run_tool_context_compaction_gate_if_needed(executions)
                                append_mid_turn_user_messages(self)
                                return self.Send(
                                    tools=tools,
                                    run_tools=run_tools,
                                    mode=mode,
                                    web_search=web_search,
                                    thinking=thinking,
                                    stream=stream,
                                    stream_handler=stream_handler,
                                )
                            return {"type": "function_call", "function": function_calls[0]}

                        image_paths = self.save_inline_images(parts, filename_prefix="generated_image")
                        compaction_gate_active = getattr(self, "_tool_context_compaction_gate_active_now", None)
                        if callable(compaction_gate_active) and compaction_gate_active():
                            final_response = text_content if has_text else image_paths
                            finish_gate = getattr(self, "_finish_tool_context_compaction_gate_with_response", None)
                            if not callable(finish_gate) or not finish_gate(final_response):
                                self._retry_tool_context_compaction_gate(
                                    "the model returned an empty response instead of calling compact_tool_context"
                                )
                                return self.Send(
                                    tools=tools,
                                    run_tools=run_tools,
                                    mode=mode,
                                    web_search=web_search,
                                    thinking=thinking,
                                    stream=stream,
                                    stream_handler=stream_handler,
                                )

                        if has_text:
                            self.Message("assistant", text_content)
                            if stream:
                                self._emit_stream_text(stream_handler, "", text_content)
                        if image_paths:
                            response_text = text_content if has_text else f"Image generated successfully: {', '.join(image_paths)}"
                            return {
                                "response": response_text,
                                "image_path": image_paths[0] if len(image_paths) == 1 else image_paths,
                            }
                        if has_text:
                            return text_content
                    else:
                        return f"Error: No content in candidate. Finish reason: {candidate.get('finishReason')}"
                else:
                    return f"Error: Unexpected response format: {json.dumps(result, ensure_ascii=False)}"
            except urllib.error.HTTPError as e:
                error_content = e.read().decode("utf-8")
                error_msg = f"HTTP Error: {e.code} - {error_content}"
                if attempt < max_retries:
                    time.sleep(retry_delay + random.uniform(0, 0.5))
                    retry_delay *= 2
                    continue
                self.RuntimeInstruction(f"Gemini API Error: {error_msg}")
                return error_msg
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries:
                    time.sleep(retry_delay + random.uniform(0, 0.5))
                    retry_delay *= 2
                    continue
                self.RuntimeInstruction(f"Gemini Internal Error: {error_str}")
                return f"Error: {error_str}"
