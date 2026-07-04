from __future__ import annotations

from typing import Any

from src.providers.responses_input_items import build_responses_function_call_input_item
from src.providers.responses_input_items import build_responses_function_call_output_item
from src.providers.responses_input_items import build_responses_message_input_item
from src.service_host import HostBoundService
from src.tool.tool_call_protocol import ToolCallEnvelope
from src.tool.tool_call_protocol import ToolCallParseFailure


class ResponsesMapping(HostBoundService):
    def _responses_message_roles(self) -> set[str]:
        return {"system", "developer", "user", "assistant"}

    def _responses_text_part_type(self, role: str) -> str:
        return "output_text" if role == "assistant" else "input_text"

    def _responses_include_refusal_parts(self) -> bool:
        return True

    def _responses_tool_message_output(self, *, tool_name: str, call_id: str, content: Any) -> Any:
        _ = tool_name, call_id
        return content

    def _message_to_responses_input_item(self, message):
        if not isinstance(message, dict):
            return None
        role = str(message.get("role") or "").strip().lower()
        content = message.get("content")
        if role in self._responses_message_roles():
            if role == "assistant" and isinstance(message.get("tool_calls"), list) and message.get("tool_calls"):
                items = []
                content_item = self._message_content_to_responses_item(role, content)
                if content_item is not None:
                    items.append(content_item)
                items.extend(self._openai_tool_calls_to_responses_items(message.get("tool_calls")))
                return items or None
            return self._message_content_to_responses_item(role, content)
        if role == "tool":
            call_id = str(message.get("tool_call_id") or message.get("call_id") or "").strip()
            if not call_id:
                return None
            tool_name = str(message.get("name") or "").strip() or "tool"
            output = self._responses_tool_message_output(
                tool_name=tool_name,
                call_id=call_id,
                content=content,
            )
            return build_responses_function_call_output_item(call_id, output)
        return None

    def _message_content_to_responses_item(self, role, content):
        if role not in self._responses_message_roles():
            return None
        text_part_type = self._responses_text_part_type(role)
        parts = []
        if isinstance(content, str):
            if content.strip():
                parts.append({"type": text_part_type, "text": content})
        elif isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "").strip().lower()
                if item_type in {"text", "input_text", "output_text"}:
                    text = str(item.get("text") or "").strip()
                    if text:
                        parts.append({"type": text_part_type, "text": text})
                elif role == "assistant" and item_type == "refusal" and self._responses_include_refusal_parts():
                    refusal = str(item.get("refusal") or item.get("text") or "").strip()
                    if refusal:
                        parts.append({"type": "refusal", "refusal": refusal})
                elif item_type == "image_url":
                    image_url = item.get("image_url")
                    url = str((image_url or {}).get("url") or "").strip() if isinstance(image_url, dict) else ""
                    if url:
                        parts.append({"type": "input_image", "image_url": url})
                elif item_type == "input_image":
                    url = str(item.get("image_url") or "").strip()
                    if url:
                        parts.append({"type": "input_image", "image_url": url})
        if not parts:
            return None
        return build_responses_message_input_item(role=role, content=parts)

    def _openai_tool_calls_to_responses_items(self, tool_calls):
        items = []
        for call in tool_calls if isinstance(tool_calls, list) else []:
            if not isinstance(call, dict):
                continue
            function_item = call.get("function")
            if not isinstance(function_item, dict):
                continue
            call_id = str(call.get("id") or "").strip()
            name = str(function_item.get("name") or "").strip()
            if not call_id or not name:
                continue
            item_id = str(call.get("item_id") or call.get("output_item_id") or "").strip()
            status = str(call.get("status") or "").strip()
            items.append(
                build_responses_function_call_input_item(
                    call_id=call_id,
                    name=name,
                    arguments=function_item.get("arguments") if function_item.get("arguments") is not None else {},
                    item_id=item_id,
                    status=status,
                )
            )
        return items

    def _build_responses_input(self, messages):
        items = []
        for message in messages if isinstance(messages, list) else []:
            item = self._message_to_responses_input_item(message)
            if isinstance(item, list):
                items.extend(item)
            elif item is not None:
                items.append(item)
        return items

    def _build_responses_function_call_input_items(self, function_calls):
        items = []
        for call in function_calls if isinstance(function_calls, list) else []:
            if not isinstance(call, (ToolCallEnvelope, ToolCallParseFailure)):
                continue
            raw = call.raw if isinstance(call.raw, dict) else {}
            item_id = str(raw.get("id") or "").strip()
            status = str(raw.get("status") or "").strip()
            items.append(
                build_responses_function_call_input_item(
                    call_id=call.call_id,
                    name=call.name,
                    arguments=call.arguments_json,
                    item_id=item_id,
                    status=status,
                )
            )
        return items
