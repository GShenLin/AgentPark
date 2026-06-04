import json
from dataclasses import dataclass
from typing import Any

from src.providers.provider_errors import ProviderImageAttachmentError
from src.service_host import HostBoundService
from src.tool_call_protocol import ToolCallEnvelope
from src.tool_call_protocol import build_tool_call_error_execution
from src.tool_call_protocol import ensure_json_text
from src.tool_call_protocol import from_openai_tool_call
from src.tool_call_protocol import to_openai_tool_call


@dataclass(frozen=True)
class TaggedFunctionCallParseResult:
    visible_text: str
    calls: list[dict[str, Any]]
    diagnostics: tuple[str, ...] = ()


class DoubaoToolRuntime(HostBoundService):
    _FUNCTION_CALL_BEGIN = "<|FunctionCallBegin|>"
    _FUNCTION_CALL_END = "<|FunctionCallEnd|>"

    def _inject_image_message(self, image_path, base64_data=None, text=None):
        import base64
        import os

        encoded_string = None
        if base64_data:
            encoded_string = base64_data
            if isinstance(encoded_string, bytes):
                encoded_string = encoded_string.decode("utf-8")
        else:
            safe_path = str(image_path or "").strip()
            if not safe_path:
                raise ProviderImageAttachmentError("image path is required when base64 data is not provided")
            if not os.path.exists(safe_path):
                raise ProviderImageAttachmentError(f"image file not found: {safe_path}")
            try:
                with open(safe_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            except Exception as exc:
                raise ProviderImageAttachmentError(
                    f"failed to read image file {safe_path}: {type(exc).__name__}: {exc}"
                ) from exc

        if not isinstance(encoded_string, str) or not encoded_string.strip():
            raise ProviderImageAttachmentError("image data is empty")

        description = f"[System] User provided an image: {image_path}"
        if hasattr(self, "_append_memory"):
            self._append_memory("user", description)

        message_content = []
        text_value = str(text or "").strip()
        if text_value:
            message_content.append({"type": "text", "text": text_value})
        message_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded_string}"},
            }
        )
        self.messages.append({"role": "user", "content": message_content})

    def _execute_tool_calls_parallel(self, tool_calls):
        if not isinstance(tool_calls, list) or not tool_calls:
            return []
        envelopes = self._normalize_openai_tool_calls(tool_calls)
        return self._execute_tool_call_envelopes_parallel(envelopes)

    def _execute_tool_call_envelopes_parallel(self, tool_calls):
        if not isinstance(tool_calls, list) or not tool_calls:
            return []
        if not all(isinstance(item, ToolCallEnvelope) for item in tool_calls):
            raise TypeError("_execute_tool_call_envelopes_parallel requires ToolCallEnvelope items")

        def _run_single_tool(tool_call):
            return self.tools.execute_tool_call(tool_call)

        def _task_meta(tool_call):
            return tool_call.name, tool_call.call_id

        def _build_error_result(tool_call, error, _index):
            return build_tool_call_error_execution(
                tool_call,
                status="error",
                error=f"{type(error).__name__}: {error}",
            )

        def _build_timeout_result(tool_call, timeout_seconds, _index):
            return build_tool_call_error_execution(
                tool_call,
                status="timeout",
                error=f"Tool worker exceeded {timeout_seconds:.2f}s.",
            )

        return self._execute_tasks_parallel_ordered(
            tasks=tool_calls,
            run_task=_run_single_tool,
            task_to_meta=_task_meta,
            build_error_result=_build_error_result,
            build_timeout_result=_build_timeout_result,
        )

    def _normalize_openai_tool_calls(self, tool_calls):
        envelopes = []
        for item in tool_calls if isinstance(tool_calls, list) else []:
            call = from_openai_tool_call(item, provider="doubao_chat")
            if call is not None:
                envelopes.append(call)
        return envelopes

    def _extract_tool_calls(self, message):
        if not isinstance(message, dict):
            return []
        raw_tool_calls = message.get("tool_calls")
        if isinstance(raw_tool_calls, list):
            valid = [to_openai_tool_call(call) for call in self._normalize_openai_tool_calls(raw_tool_calls)]
            if valid:
                return valid
        return []

    def _pick_response_message(self, choices, run_tools):
        if not isinstance(choices, list) or not choices:
            return None, None
        if run_tools:
            for idx, choice in enumerate(choices):
                msg = (choice or {}).get("message")
                if self._extract_tool_calls(msg):
                    return msg, idx
        first = choices[0] or {}
        return first.get("message"), 0

    @staticmethod
    def _ensure_json_text(value):
        return ensure_json_text(value)

    def _parse_tagged_function_calls_from_text(self, content) -> TaggedFunctionCallParseResult:
        text = str(content or "")
        begin = self._FUNCTION_CALL_BEGIN
        end = self._FUNCTION_CALL_END
        if begin not in text:
            return TaggedFunctionCallParseResult(visible_text=text, calls=[])

        cursor = 0
        visible_parts: list[str] = []
        parsed_calls: list[dict] = []
        diagnostics: list[str] = []
        while cursor < len(text):
            start = text.find(begin, cursor)
            if start < 0:
                visible_parts.append(text[cursor:])
                break
            visible_parts.append(text[cursor:start])
            payload_start = start + len(begin)
            payload_end = text.find(end, payload_start)
            if payload_end < 0:
                visible_parts.append(text[start:])
                diagnostics.append("tagged function call begin marker has no matching end marker")
                break

            payload_text = text[payload_start:payload_end].strip()
            cursor = payload_end + len(end)
            if not payload_text:
                diagnostics.append("tagged function call payload is empty")
                continue

            try:
                payload_obj = json.loads(payload_text)
            except json.JSONDecodeError as exc:
                diagnostics.append(f"tagged function call payload is invalid JSON: {exc}")
                continue

            if isinstance(payload_obj, dict):
                payload_items = [payload_obj]
            elif isinstance(payload_obj, list):
                payload_items = payload_obj
            else:
                payload_items = []
                diagnostics.append(
                    f"tagged function call payload must be object or array, got {type(payload_obj).__name__}"
                )

            for index, item in enumerate(payload_items):
                if not isinstance(item, dict):
                    diagnostics.append(
                        f"tagged function call item {index} must be object, got {type(item).__name__}"
                    )
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    function_item = item.get("function")
                    if isinstance(function_item, dict):
                        name = str(function_item.get("name") or "").strip()
                if not name:
                    diagnostics.append(f"tagged function call item {index} is missing function name")
                    continue

                args_raw = None
                if "parameters" in item:
                    args_raw = item.get("parameters")
                elif "arguments" in item:
                    args_raw = item.get("arguments")
                elif "args" in item:
                    args_raw = item.get("args")
                else:
                    function_item = item.get("function")
                    if isinstance(function_item, dict):
                        if "arguments" in function_item:
                            args_raw = function_item.get("arguments")
                        elif "parameters" in function_item:
                            args_raw = function_item.get("parameters")

                parsed_calls.append(
                    {
                        "id": str(item.get("id") or item.get("call_id") or "").strip(),
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": self._ensure_json_text(args_raw if args_raw is not None else {}),
                        },
                    }
                )

        return TaggedFunctionCallParseResult(
            visible_text="".join(visible_parts),
            calls=parsed_calls,
            diagnostics=tuple(diagnostics),
        )

    def _normalize_message_tool_calls(self, message):
        if not isinstance(message, dict):
            return message
        if self._extract_tool_calls(message):
            return message
        parse_result = self._parse_tagged_function_calls_from_text(message.get("content"))
        if parse_result.diagnostics:
            self._emit_tagged_function_call_diagnostics(parse_result.diagnostics)
        if not parse_result.calls:
            if parse_result.diagnostics and parse_result.visible_text != str(message.get("content") or ""):
                normalized = dict(message)
                normalized["content"] = parse_result.visible_text
                return normalized
            return message
        normalized = dict(message)
        normalized["content"] = parse_result.visible_text
        normalized["tool_calls"] = parse_result.calls
        return normalized

    def _emit_tagged_function_call_diagnostics(self, diagnostics: tuple[str, ...]) -> None:
        callback = getattr(self, "tool_event_callback", None)
        if not callable(callback):
            return
        for diagnostic in diagnostics:
            callback(
                {
                    "type": "runtime_notice",
                    "source": "provider_tool_call_parser",
                    "stage": "normalize_message_tool_calls",
                    "provider": "doubao",
                    "message": diagnostic,
                }
            )
