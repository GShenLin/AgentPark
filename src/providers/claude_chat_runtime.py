from __future__ import annotations

import json
from typing import Any

from src.providers.curl_transport import CurlHttpTransport, CurlTransportError
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.providers.provider_stream_emit import ProviderStreamEmitMixin
from src.providers.tool_call_execution import execute_tool_call_items_parallel
from src.providers.tool_call_execution import parse_openai_tool_call_items
from src.providers.tool_call_runtime import ToolCallExecutionMixin
from src.runtime_cancellation import CancellationRequested
from src.runtime_cancellation import sleep_with_cancel
from src.service_host import HostBoundService
from src.tool.tool_call_protocol import to_openai_tool_call


class ClaudeChatRuntime(ProviderStreamEmitMixin, ToolCallExecutionMixin, ProviderRuntimeEventMixin, CurlHttpTransport, HostBoundService):
    def to_claude_tool_declarations(self, tools) -> list[dict]:
        if not isinstance(tools, list):
            raise ValueError("Claude tools must be a list of tool declarations.")
        return [self.to_claude_tool_declaration(tool) for tool in tools]

    def to_claude_tool_declaration(self, tool) -> dict:
        if not isinstance(tool, dict):
            raise ValueError("Claude tool declaration must be an object.")
        if self._is_claude_tool_declaration(tool):
            return {
                "name": str(tool["name"]).strip(),
                "description": str(tool.get("description") or ""),
                "input_schema": dict(tool["input_schema"]),
            }
        function_decl = tool.get("function")
        if not isinstance(function_decl, dict):
            raise ValueError("Claude tool declaration requires either name/input_schema or OpenAI function metadata.")
        name = str(function_decl.get("name") or "").strip()
        if not name:
            raise ValueError("Claude tool declaration function.name is required.")
        parameters = function_decl.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError(f"Claude tool declaration {name!r} requires function.parameters object.")
        return {
            "name": name,
            "description": str(function_decl.get("description") or ""),
            "input_schema": dict(parameters),
        }

    @staticmethod
    def _is_claude_tool_declaration(tool: dict) -> bool:
        name = str(tool.get("name") or "").strip()
        return bool(name and isinstance(tool.get("input_schema"), dict))

    def build_claude_messages_payload(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict] | None,
        web_search_mode: str,
        thinking_mode: str | None,
        reasoning_effort: object,
    ) -> dict[str, Any]:
        system, claude_messages = self._map_messages_to_claude(messages)
        max_tokens = self._claude_max_tokens()
        payload: dict[str, Any] = {
            "model": self.config["model"],
            "max_tokens": max_tokens,
            "messages": claude_messages,
        }
        if system:
            payload["system"] = system
        merged_tools = list(tools or [])
        if web_search_mode == "enabled":
            merged_tools.append(self._build_claude_web_search_tool())
        if merged_tools:
            payload["tools"] = merged_tools
        thinking_payload = self._build_claude_thinking(thinking_mode, max_tokens=max_tokens)
        if thinking_payload:
            payload["thinking"] = thinking_payload
        effort_payload = self._build_claude_output_config(reasoning_effort)
        if effort_payload:
            payload["output_config"] = effort_payload
        return payload

    def _claude_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": str(self.config["apiKey"]),
            "anthropic-version": str(self.config.get("anthropicVersion") or "2023-06-01"),
        }
        beta = str(self.config.get("anthropicBeta") or self.config.get("anthropic_beta") or "").strip()
        if beta:
            headers["anthropic-beta"] = beta
        return headers

    def _messages_url(self) -> str:
        base_url = str(self.config["baseUrl"]).rstrip("/")
        if base_url.endswith("/messages"):
            return base_url
        return f"{base_url}/messages"

    def send_messages(self, payload: dict, *, stream: bool = False, stream_handler=None, thinking_stream_handler=None) -> dict:
        headers = self._claude_headers()
        request_payload = dict(payload)
        use_stream = bool(stream and (callable(stream_handler) or callable(thinking_stream_handler)))
        if use_stream:
            request_payload["stream"] = True
        payload_json = json.dumps(request_payload, ensure_ascii=False)
        url = self._messages_url()
        if use_stream:
            max_retries = int(self.config.get("maxRetries", self.config.get("max_retries", 3)))
            retry_delay = float(self.config.get("retryDelaySec", self.config.get("retry_delay_sec", 1)))
            return self._stream_messages_with_retry(
                endpoint="messages",
                url=url,
                headers=headers,
                payload_json=payload_json,
                max_retries=max_retries,
                retry_delay=retry_delay,
                stream_handler=stream_handler if callable(stream_handler) else None,
                thinking_stream_handler=thinking_stream_handler if callable(thinking_stream_handler) else None,
            )
        result = self.post_json_with_retry(endpoint="messages", url=url, headers=headers, payload_json=payload_json)
        return self._normalize_claude_response(result)

    def post_json_with_retry(self, *, endpoint, url, headers, payload_json):
        timeout = self.config.get("timeoutMs", 60000) / 1000
        max_retries = int(self.config.get("maxRetries", self.config.get("max_retries", 3)))
        retry_delay = float(self.config.get("retryDelaySec", self.config.get("retry_delay_sec", 1)))
        for attempt in range(max(0, max_retries) + 1):
            try:
                response = self._curl_post_once_raw(
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    timeout_sec=timeout,
                    marker="__CLAUDE_HTTP_CODE__:",
                )
                if response.status_code < 200 or response.status_code >= 300:
                    raise RuntimeError(f"{endpoint}: HTTP {response.status_code}: {response.body}")
                return json.loads(response.body)
            except CancellationRequested:
                raise
            except CurlTransportError as exc:
                error_text = f"{endpoint}: {exc}"
            except json.JSONDecodeError as exc:
                error_text = f"{endpoint}: invalid JSON response: {exc}"
            except Exception as exc:
                error_text = str(exc)
            if attempt < max_retries:
                self._emit_retry_notice(error=error_text, delay=retry_delay, stage="claude_messages_retry")
                sleep_with_cancel(retry_delay, self._cancel_source())
                continue
            raise RuntimeError(error_text)
        raise RuntimeError(f"{endpoint}: max retries exceeded")

    def _map_messages_to_claude(self, messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        mapped: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                raise ValueError("Claude messages must contain only objects.")
            role = str(message.get("role") or "").strip().lower()
            if role in {"system", "developer"}:
                text = self._message_content_text(message.get("content")).strip()
                if text:
                    system_parts.append(text)
                continue
            if role == "tool":
                mapped.append({"role": "user", "content": [self._tool_result_block(message)]})
                continue
            if role == "assistant":
                content = self._assistant_content_blocks(message)
                if content:
                    mapped.append({"role": "assistant", "content": content})
                continue
            if role == "user":
                content = self._user_content_blocks(message.get("content"))
                if content:
                    mapped.append({"role": "user", "content": content})
                continue
            raise ValueError(f"Claude does not accept message role: {role or '<empty>'}")
        return "\n\n".join(system_parts), mapped

    def _assistant_content_blocks(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        native_blocks = message.get("_claude_content_blocks")
        if isinstance(native_blocks, list):
            blocks = [dict(block) for block in native_blocks if isinstance(block, dict) and str(block.get("type") or "").strip()]
            if blocks:
                return blocks

        blocks: list[dict[str, Any]] = []
        text = self._message_content_text(message.get("content")).strip()
        if text:
            blocks.append({"type": "text", "text": text})
        for tool_call in message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []:
            parsed = parse_openai_tool_call_items([tool_call], provider="claude_message_history")
            if not parsed:
                continue
            item = parsed[0]
            blocks.append(
                {
                    "type": "tool_use",
                    "id": item.call_id,
                    "name": item.name,
                    "input": item.arguments,
                }
            )
        return blocks

    def _user_content_blocks(self, content: object) -> list[dict[str, Any]]:
        if isinstance(content, list):
            blocks: list[dict[str, Any]] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "").strip().lower()
                if part_type == "text":
                    text = str(part.get("text") or "")
                    if text:
                        blocks.append({"type": "text", "text": text})
                    continue
                if part_type in {"image_url", "input_image"}:
                    block = self._image_part_to_claude(part)
                    if block:
                        blocks.append(block)
            return blocks
        text = self._message_content_text(content)
        return [{"type": "text", "text": text}] if text else []

    @staticmethod
    def _message_content_text(content: object) -> str:
        if isinstance(content, str):
            return content
        if content is None:
            return ""
        if isinstance(content, list):
            texts = [str(item.get("text") or "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
            return "\n".join(item for item in texts if item)
        return json.dumps(content, ensure_ascii=False)

    @staticmethod
    def _tool_result_block(message: dict[str, Any]) -> dict[str, Any]:
        content = message.get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        return {
            "type": "tool_result",
            "tool_use_id": str(message.get("tool_call_id") or ""),
            "content": text,
        }

    @staticmethod
    def _image_part_to_claude(part: dict[str, Any]) -> dict[str, Any] | None:
        url = ""
        if str(part.get("type") or "").strip().lower() == "input_image":
            url = str(part.get("image_url") or "").strip()
        else:
            image_url = part.get("image_url")
            url = str((image_url or {}).get("url") or "").strip() if isinstance(image_url, dict) else ""
        if not url:
            return None
        if url.startswith("data:") and ";base64," in url:
            header, data = url.split(";base64,", 1)
            media_type = header.removeprefix("data:") or "image/png"
            return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
        return {"type": "image", "source": {"type": "url", "url": url}}

    def _claude_max_tokens(self) -> int:
        value = self.config.get("maxTokens", self.config.get("max_tokens", 4096))
        try:
            parsed = int(value)
        except Exception as exc:
            raise ValueError("Claude maxTokens must be an integer.") from exc
        if parsed <= 0:
            raise ValueError("Claude maxTokens must be greater than zero.")
        return parsed

    def _build_claude_thinking(self, thinking_mode: str | None, *, max_tokens: int) -> dict[str, Any] | None:
        mode = str(thinking_mode or "").strip().lower()
        if mode in {"", "disabled"}:
            return None
        if mode == "auto":
            return {"type": "adaptive"}
        if mode != "enabled":
            raise ValueError("Claude thinking must be enabled, disabled, or auto.")
        budget = self.config.get("thinkingBudgetTokens", self.config.get("claudeThinkingBudgetTokens", 1024))
        try:
            budget_tokens = int(budget)
        except Exception as exc:
            raise ValueError("Claude thinkingBudgetTokens must be an integer.") from exc
        if budget_tokens <= 0 or budget_tokens >= max_tokens:
            raise ValueError("Claude thinkingBudgetTokens must be greater than zero and less than maxTokens.")
        return {"type": "enabled", "budget_tokens": budget_tokens}

    @staticmethod
    def _build_claude_output_config(reasoning_effort: object) -> dict[str, Any] | None:
        effort = str(reasoning_effort or "").strip().lower()
        if not effort:
            return None
        if effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Claude reasoning_effort maps to output_config.effort and must be low, medium, high, xhigh, or max.")
        return {"effort": effort}

    def _build_claude_web_search_tool(self) -> dict[str, Any]:
        tool = {
            "type": str(self.config.get("webSearchToolType") or self.config.get("claudeWebSearchToolType") or "web_search_20260318"),
            "name": "web_search",
        }
        limit = self.config.get("webSearchLimit", self.config.get("claudeWebSearchMaxUses"))
        if limit not in {None, ""}:
            tool["max_uses"] = int(limit)
        allowed = self._string_list_config("webSearchAllowedDomains", "claudeWebSearchAllowedDomains", "webSearchSources")
        blocked = self._string_list_config("webSearchBlockedDomains", "claudeWebSearchBlockedDomains")
        if allowed and blocked:
            raise ValueError("Claude web search accepts allowed_domains or blocked_domains, not both.")
        if allowed:
            tool["allowed_domains"] = allowed
        if blocked:
            tool["blocked_domains"] = blocked
        allowed_callers = self._string_list_config("webSearchAllowedCallers", "claudeWebSearchAllowedCallers")
        if allowed_callers:
            tool["allowed_callers"] = allowed_callers
        user_location = self.config.get("webSearchUserLocation", self.config.get("claudeWebSearchUserLocation"))
        if isinstance(user_location, dict) and user_location:
            tool["user_location"] = dict(user_location)
        response_inclusion = str(self.config.get("webSearchResponseInclusion", self.config.get("claudeWebSearchResponseInclusion", "")) or "").strip()
        if response_inclusion:
            tool["response_inclusion"] = response_inclusion
        return tool

    def _string_list_config(self, *keys: str) -> list[str]:
        for key in keys:
            value = self.config.get(key)
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, str) and value.strip():
                return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]
        return []

    def _normalize_claude_response(self, result: dict[str, Any]) -> dict[str, Any]:
        text_chunks: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        native_blocks: list[dict[str, Any]] = []
        for block in result.get("content") if isinstance(result.get("content"), list) else []:
            if not isinstance(block, dict):
                continue
            native_blocks.append(dict(block))
            block_type = str(block.get("type") or "").strip().lower()
            if block_type == "text":
                text = str(block.get("text") or "")
                if text:
                    text_chunks.append(text)
            elif block_type == "tool_use":
                name = str(block.get("name") or "").strip()
                if name:
                    tool_calls.append(
                        {
                            "id": str(block.get("id") or ""),
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(block.get("input") if isinstance(block.get("input"), dict) else {}, ensure_ascii=False),
                            },
                        }
                    )
        message: dict[str, Any] = {"role": "assistant", "content": "".join(text_chunks)}
        if native_blocks:
            message["_claude_content_blocks"] = native_blocks
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {"choices": [{"message": message}]}

    def extract_tool_calls(self, message):
        if not isinstance(message, dict):
            return []
        raw_tool_calls = message.get("tool_calls")
        if isinstance(raw_tool_calls, list):
            valid = [
                to_openai_tool_call(call)
                for call in parse_openai_tool_call_items(raw_tool_calls, provider="claude_messages")
            ]
            return [item for item in valid if item]
        return []

    def execute_tool_calls_parallel(self, tool_calls):
        items = parse_openai_tool_call_items(tool_calls, provider="claude_messages")
        if not items:
            return []
        return execute_tool_call_items_parallel(
            tool_call_items=items,
            execute_tool_call_envelopes=self._execute_tool_call_envelopes_parallel,
        )

    def pick_response_message(self, choices, run_tools):
        if not isinstance(choices, list) or not choices:
            return None, None
        if run_tools:
            for idx, choice in enumerate(choices):
                msg = (choice or {}).get("message")
                if self.extract_tool_calls(msg):
                    return msg, idx
        first = choices[0] or {}
        return first.get("message"), 0
