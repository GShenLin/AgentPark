import json
import os
from datetime import datetime


class DoubaoSseDebugMixin:
    @staticmethod
    def _debug_preview(value, limit=1000):
        text = "" if value is None else str(value)
        if len(text) <= limit:
            return text, False
        return text[:limit], True

    def _summarize_chat_payload_for_debug(self, payload_json):
        try:
            payload = json.loads(str(payload_json or ""))
        except Exception:
            return {"payload_parse_error": True}
        if not isinstance(payload, dict):
            return {"payload_type": type(payload).__name__}

        messages = []
        for item in payload.get("messages") if isinstance(payload.get("messages"), list) else []:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            content_preview = ""
            content_truncated = False
            if isinstance(content, str):
                content_preview, content_truncated = self._debug_preview(content)
                content_type = "string"
                content_length = len(content)
            elif content is None:
                content_type = "none"
                content_length = 0
            else:
                content_type = type(content).__name__
                content_length = len(content) if hasattr(content, "__len__") else 0

            tool_calls = []
            for call in item.get("tool_calls") if isinstance(item.get("tool_calls"), list) else []:
                fn = call.get("function") if isinstance(call, dict) else None
                tool_calls.append(
                    {
                        "id": str((call or {}).get("id") or "") if isinstance(call, dict) else "",
                        "name": str((fn or {}).get("name") or "") if isinstance(fn, dict) else "",
                    }
                )

            messages.append(
                {
                    "role": str(item.get("role") or ""),
                    "name": str(item.get("name") or ""),
                    "tool_call_id": str(item.get("tool_call_id") or ""),
                    "content_type": content_type,
                    "content_length": content_length,
                    "content_preview": content_preview,
                    "content_truncated": content_truncated,
                    "tool_calls": tool_calls,
                }
            )

        tools = []
        for tool in payload.get("tools") if isinstance(payload.get("tools"), list) else []:
            if not isinstance(tool, dict):
                continue
            fn = tool.get("function")
            name = ""
            if isinstance(fn, dict):
                name = str(fn.get("name") or "")
            elif tool.get("name"):
                name = str(tool.get("name") or "")
            tools.append({"type": str(tool.get("type") or ""), "name": name})

        return {
            "model": str(payload.get("model") or ""),
            "stream": bool(payload.get("stream")),
            "thinking": payload.get("thinking") if isinstance(payload.get("thinking"), dict) else None,
            "message_count": len(messages),
            "messages": messages,
            "tools": tools,
        }

    def _chat_payload_has_tool_context(self, payload_json):
        summary = self._summarize_chat_payload_for_debug(payload_json)
        for message in summary.get("messages") if isinstance(summary, dict) else []:
            if not isinstance(message, dict):
                continue
            if message.get("role") == "tool" or message.get("tool_call_id"):
                return True
            if message.get("tool_calls"):
                return True
        return False

    def _build_chat_sse_debug_event(self, *, index, raw_data, parsed_event):
        raw_preview, raw_truncated = self._debug_preview(raw_data, limit=20000)
        record = {
            "index": index,
            "raw": raw_preview,
            "raw_truncated": raw_truncated,
            "parsed_type": type(parsed_event).__name__ if parsed_event is not None else "none",
        }
        if not isinstance(parsed_event, dict):
            return record

        choices = parsed_event.get("choices")
        record["object"] = str(parsed_event.get("object") or "")
        record["event_type"] = str(parsed_event.get("type") or "")
        record["choice_count"] = len(choices) if isinstance(choices, list) else 0
        choice_summaries = []
        for choice in choices if isinstance(choices, list) else []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            message = choice.get("message")
            finish_reason = choice.get("finish_reason")
            delta_keys = sorted(delta.keys()) if isinstance(delta, dict) else []
            message_keys = sorted(message.keys()) if isinstance(message, dict) else []
            delta_content = delta.get("content") if isinstance(delta, dict) else None
            reasoning_content = delta.get("reasoning_content") if isinstance(delta, dict) else None
            content_preview, content_truncated = self._debug_preview(delta_content, limit=1000)
            reasoning_preview, reasoning_truncated = self._debug_preview(reasoning_content, limit=1000)
            choice_summaries.append(
                {
                    "index": choice.get("index"),
                    "finish_reason": finish_reason,
                    "delta_keys": delta_keys,
                    "message_keys": message_keys,
                    "delta_content_length": len(delta_content) if isinstance(delta_content, str) else 0,
                    "delta_content_preview": content_preview,
                    "delta_content_truncated": content_truncated,
                    "reasoning_content_length": len(reasoning_content) if isinstance(reasoning_content, str) else 0,
                    "reasoning_content_preview": reasoning_preview,
                    "reasoning_content_truncated": reasoning_truncated,
                    "has_tool_calls": bool(isinstance(delta, dict) and isinstance(delta.get("tool_calls"), list)),
                }
            )
        record["choices"] = choice_summaries
        return record

    def _write_chat_sse_debug_if_needed(self, *, url, payload_json, events, assembled_message):
        content = assembled_message.get("content") if isinstance(assembled_message, dict) else None
        has_content = isinstance(content, str) and bool(content.strip())
        has_tool_calls = bool(isinstance(assembled_message, dict) and assembled_message.get("tool_calls"))
        if has_content and not has_tool_calls and not self._chat_payload_has_tool_context(payload_json):
            return

        try:
            runtime_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            debug_dir = os.path.join(runtime_root, "memories", "_http_debug")
            os.makedirs(debug_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = os.path.join(debug_dir, f"doubao_sse_chat_{ts}_{os.getpid()}.json")
            record = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                "provider": str(getattr(self, "provider_name", "") or ""),
                "endpoint": "chat/completions",
                "url": str(url or ""),
                "request": self._summarize_chat_payload_for_debug(payload_json),
                "sse": {
                    "event_count": len(events) if isinstance(events, list) else 0,
                    "events": events if isinstance(events, list) else [],
                },
                "assembled_message": assembled_message,
            }
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
        except Exception:
            return
