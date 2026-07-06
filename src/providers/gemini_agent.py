import json
import random
import time
import urllib.error
import urllib.request

from src.base_agent import BaseAgent
from src.providers.provider_errors import ProviderImageAttachmentError
from src.providers.gemini_function_runtime import GeminiFunctionRuntime
from src.providers.gemini_image_generation import GeminiImageGeneration
from src.providers.gemini_stream_runtime import GeminiStreamRuntime
from src.providers.mid_turn_user_inputs import append_mid_turn_user_messages
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

    @staticmethod
    def _build_function_response_content(content):
        if not isinstance(content, str):
            return {"result": content}
        text = content.strip()
        if not text or not text.startswith("{"):
            return {"result": content}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"result": content}
        if isinstance(parsed, dict):
            return parsed
        return {"result": content}

    def Send(
        self,
        tools=None,
        run_tools=True,
        mode="chat",
        web_search=None,
        thinking=None,
        stream=False,
        stream_handler=None,
    ):
        self.config = self._read_provider_config_from_file()
        _ = web_search
        _ = thinking
        if mode == "image_generation":
            prompt = self._extract_latest_user_prompt(self.messages)
            if not prompt:
                return "Error: No prompt found for image generation."

            try:
                result = self.generate_image(prompt)
                if isinstance(result, dict) and result.get("image_path"):
                    return f"Image generated successfully: {result['image_path']}"
                return str(result)
            except Exception as e:
                return f"Image generation failed: {str(e)}"

        messages = self._get_messages_with_memory()
        gemini_contents = []
        system_instruction = None

        for msg in messages:
            role = msg["role"]
            content = msg.get("content")

            if role == "system":
                if system_instruction is None:
                    system_instruction = {"parts": [{"text": content}]}
                elif isinstance(content, dict) and content.get("type") == "image_data":
                    text = content.get("text", "")
                    base64_data = content.get("data")
                    mime_type = content.get("mime_type", "image/png")
                    parts = []
                    if text:
                        parts.append({"text": text})
                    parts.append(
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64_data,
                            }
                        }
                    )
                    system_instruction.setdefault("parts", []).extend(parts)
                else:
                    system_instruction["parts"][0]["text"] += "\n" + str(content)
            elif role == "user":
                parts = []
                if isinstance(content, dict) and content.get("type") == "image":
                    image_path = content.get("path")
                    text = content.get("text", "")
                    if text:
                        parts.append({"text": text})
                    try:
                        with open(image_path, "rb") as img_file:
                            import base64

                            b64_data = base64.b64encode(img_file.read()).decode("utf-8")
                        parts.append(
                            {
                                "inline_data": {
                                    "mime_type": "image/png",
                                    "data": b64_data,
                                }
                            }
                        )
                    except Exception as exc:
                        raise ProviderImageAttachmentError(
                            f"failed to read image file {image_path}: {type(exc).__name__}: {exc}"
                        ) from exc
                elif isinstance(content, dict) and content.get("type") == "image_data":
                    text = content.get("text", "")
                    base64_data = content.get("data")
                    mime_type = content.get("mime_type", "image/png")
                    if text:
                        parts.append({"text": text})
                    parts.append(
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64_data,
                            }
                        }
                    )
                else:
                    parts.append({"text": str(content)})

                gemini_contents.append(
                    {
                        "role": "user",
                        "parts": parts,
                    }
                )
            elif role == "assistant":
                if "parts" in msg:
                    gemini_contents.append({"role": "model", "parts": msg["parts"]})
                else:
                    gemini_contents.append({"role": "model", "parts": [{"text": content}]})
            elif role == "function":
                response_content = self._build_function_response_content(content)

                gemini_contents.append(
                    {
                        "role": "function",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": msg.get("name"),
                                    "response": response_content,
                                }
                            }
                        ],
                    }
                )

        payload = {"contents": gemini_contents}
        if system_instruction:
            payload["system_instruction"] = system_instruction

        active_tools = tools if tools else (self.tool_declarations if self.tool_declarations else None)
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
                            self.Message("assistant", text_content if has_text else None, parts=parts)
                            if run_tools:
                                executions = self._execute_function_calls_parallel(function_calls)
                                for execution in executions:
                                    self.Message("function", execution.cleaned_result, name=execution.func_name)
                                    non_retry_warn = self._build_non_retryable_tool_warning(
                                        execution.func_name,
                                        execution.cleaned_result,
                                    )
                                    if non_retry_warn:
                                        self.Message("system", non_retry_warn)

                                    image_data = execution.image_data
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

                                if self._operational_memory_gate_completed(executions):
                                    return json.dumps({"status": "memory_gate_completed"}, ensure_ascii=False)
                                if self._tool_context_compaction_gate_completed(executions):
                                    return json.dumps({"status": "tool_context_compaction_completed"}, ensure_ascii=False)
                                self._run_operational_memory_gate_for_failed_executions(executions)
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

                        if has_text:
                            self.Message("assistant", text_content)
                            if stream:
                                self._emit_stream_text(stream_handler, "", text_content)
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
                self.Message("system", f"Gemini API Error: {error_msg}")
                return error_msg
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries:
                    time.sleep(retry_delay + random.uniform(0, 0.5))
                    retry_delay *= 2
                    continue
                self.Message("system", f"Gemini Internal Error: {error_str}")
                return f"Error: {error_str}"
