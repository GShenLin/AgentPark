import json
import os
from datetime import datetime


class ProviderSseDebugMixin:
    @staticmethod
    def _debug_preview(value, limit=1000):
        text = "" if value is None else str(value)
        if len(text) <= limit:
            return text, False
        return text[:limit], True

    def _summarize_sse_payload_for_debug(self, payload_json):
        try:
            payload = json.loads(str(payload_json or ""))
        except Exception:
            return {"payload_parse_error": True}
        if not isinstance(payload, dict):
            return {"payload_type": type(payload).__name__}

        summary = {
            "model": str(payload.get("model") or ""),
            "stream": bool(payload.get("stream")),
        }
        for key in ("reasoning", "thinking", "include", "tool_choice", "parallel_tool_calls"):
            if key in payload:
                summary[key] = payload.get(key)
        messages = self._summarize_sse_message_items(payload.get("messages"))
        if messages:
            summary["message_count"] = len(messages)
            summary["messages"] = messages
        input_items = self._summarize_sse_input_items(payload.get("input"))
        if input_items:
            summary["input_count"] = len(input_items)
            summary["input"] = input_items
        tools = self._summarize_sse_tools(payload.get("tools"))
        if tools:
            summary["tools"] = tools
        return summary

    def _build_sse_debug_event(self, *, index, raw_data, parsed_event):
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
        response = parsed_event.get("response")
        item = parsed_event.get("item")
        record["object"] = str(parsed_event.get("object") or "")
        record["event_type"] = str(parsed_event.get("type") or "")
        record["keys"] = sorted(str(key) for key in parsed_event.keys())
        record["choice_count"] = len(choices) if isinstance(choices, list) else 0
        if isinstance(choices, list):
            record["choices"] = [self._summarize_sse_choice(choice) for choice in choices if isinstance(choice, dict)]
        if isinstance(item, dict):
            record["item"] = self._summarize_sse_output_item(item)
        if isinstance(response, dict):
            output = response.get("output")
            record["response"] = {
                "id": str(response.get("id") or ""),
                "status": str(response.get("status") or ""),
                "output_count": len(output) if isinstance(output, list) else 0,
                "output": [
                    self._summarize_sse_output_item(output_item)
                    for output_item in output[:20]
                    if isinstance(output_item, dict)
                ]
                if isinstance(output, list)
                else [],
            }
        return record

    def _write_sse_debug_if_needed(
        self,
        *,
        endpoint,
        url,
        payload_json,
        events,
        final_payload=None,
        filename_prefix="sse",
        force=False,
    ):
        if not force and not self._provider_sse_debug_enabled():
            return
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            debug_dir = os.path.join(root, "memories", "_http_debug")
            os.makedirs(debug_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = os.path.join(debug_dir, f"{filename_prefix}_{ts}_{os.getpid()}.json")
            record = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                "provider": str(getattr(self, "provider_name", "") or ""),
                "endpoint": str(endpoint or ""),
                "url": str(url or ""),
                "request": self._summarize_sse_payload_for_debug(payload_json),
                "sse": {
                    "event_count": len(events) if isinstance(events, list) else 0,
                    "events": events if isinstance(events, list) else [],
                },
            }
            if final_payload is not None:
                record["final_payload"] = final_payload
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
        except Exception:
            return

    def _provider_sse_debug_enabled(self) -> bool:
        config = getattr(self, "config", None)
        cfg = config if isinstance(config, dict) else {}
        return bool(cfg.get("sseDebug"))

    def _sse_payload_has_tool_context(self, payload_json) -> bool:
        summary = self._summarize_sse_payload_for_debug(payload_json)
        messages = summary.get("messages") if isinstance(summary, dict) else []
        if not isinstance(messages, list):
            messages = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("role") == "tool" or message.get("tool_call_id"):
                return True
            if message.get("tool_calls"):
                return True
        return False

    def _sse_payload_has_reasoning_or_web_search(self, payload_json) -> bool:
        summary = self._summarize_sse_payload_for_debug(payload_json)
        if not isinstance(summary, dict):
            return False
        if isinstance(summary.get("reasoning"), dict) or isinstance(summary.get("thinking"), dict):
            return True
        tools = summary.get("tools")
        if not isinstance(tools, list):
            tools = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if str(tool.get("type") or "").strip().lower() in {"web_search", "web_search_preview"}:
                return True
        return False

    def _summarize_chat_payload_for_debug(self, payload_json):
        return self._summarize_sse_payload_for_debug(payload_json)

    def _chat_payload_has_tool_context(self, payload_json):
        return self._sse_payload_has_tool_context(payload_json)

    def _build_chat_sse_debug_event(self, *, index, raw_data, parsed_event):
        return self._build_sse_debug_event(index=index, raw_data=raw_data, parsed_event=parsed_event)

    def _chat_sse_debug_filename_prefix(self):
        provider = str(getattr(self, "provider_name", "") or "provider").strip() or "provider"
        safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in provider)
        return f"{safe}_sse_chat"

    def _write_chat_sse_debug_if_needed(self, *, url, payload_json, events, assembled_message):
        content = assembled_message.get("content") if isinstance(assembled_message, dict) else None
        has_content = isinstance(content, str) and bool(content.strip())
        has_tool_calls = bool(isinstance(assembled_message, dict) and assembled_message.get("tool_calls"))
        force = (
            self._provider_sse_debug_enabled()
            or has_tool_calls
            or self._chat_payload_has_tool_context(payload_json)
            or not has_content
        )
        self._write_sse_debug_if_needed(
            endpoint="chat/completions",
            url=url,
            payload_json=payload_json,
            events=events,
            final_payload={"assembled_message": assembled_message},
            filename_prefix=self._chat_sse_debug_filename_prefix(),
            force=force,
        )

    def _summarize_sse_choice(self, choice):
        delta = choice.get("delta") if isinstance(choice, dict) else None
        message = choice.get("message") if isinstance(choice, dict) else None
        delta_keys = sorted(delta.keys()) if isinstance(delta, dict) else []
        message_keys = sorted(message.keys()) if isinstance(message, dict) else []
        delta_content = delta.get("content") if isinstance(delta, dict) else None
        reasoning_content = delta.get("reasoning_content") if isinstance(delta, dict) else None
        content_preview, content_truncated = self._debug_preview(delta_content, limit=1000)
        reasoning_preview, reasoning_truncated = self._debug_preview(reasoning_content, limit=1000)
        return {
            "index": choice.get("index"),
            "finish_reason": choice.get("finish_reason"),
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

    def _summarize_sse_message_items(self, messages_value):
        messages = []
        for item in messages_value if isinstance(messages_value, list) else []:
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
            messages.append(
                {
                    "role": str(item.get("role") or ""),
                    "name": str(item.get("name") or ""),
                    "tool_call_id": str(item.get("tool_call_id") or ""),
                    "content_type": content_type,
                    "content_length": content_length,
                    "content_preview": content_preview,
                    "content_truncated": content_truncated,
                    "tool_calls": self._summarize_sse_tool_calls(item.get("tool_calls")),
                }
            )
        return messages

    def _summarize_sse_input_items(self, input_value):
        items = []
        for item in input_value if isinstance(input_value, list) else []:
            if not isinstance(item, dict):
                continue
            summary = {"type": str(item.get("type") or ""), "status": str(item.get("status") or "")}
            for key in ("id", "call_id", "name", "role"):
                if item.get(key) is not None:
                    summary[key] = str(item.get(key) or "")
            content = item.get("content")
            if isinstance(content, list):
                summary["content_count"] = len(content)
            items.append(summary)
        return items

    @staticmethod
    def _summarize_sse_tool_calls(tool_calls_value):
        tool_calls = []
        for call in tool_calls_value if isinstance(tool_calls_value, list) else []:
            fn = call.get("function") if isinstance(call, dict) else None
            tool_calls.append(
                {
                    "id": str((call or {}).get("id") or "") if isinstance(call, dict) else "",
                    "name": str((fn or {}).get("name") or "") if isinstance(fn, dict) else "",
                }
            )
        return tool_calls

    @staticmethod
    def _summarize_sse_tools(tools_value):
        tools = []
        for tool in tools_value if isinstance(tools_value, list) else []:
            if not isinstance(tool, dict):
                continue
            fn = tool.get("function")
            name = ""
            if isinstance(fn, dict):
                name = str(fn.get("name") or "")
            elif tool.get("name"):
                name = str(tool.get("name") or "")
            tools.append({"type": str(tool.get("type") or ""), "name": name})
        return tools

    def _summarize_sse_output_item(self, item):
        item_type = str(item.get("type") or "")
        summary = {
            "type": item_type,
            "id": str(item.get("id") or ""),
            "call_id": str(item.get("call_id") or ""),
            "name": str(item.get("name") or ""),
            "status": str(item.get("status") or ""),
        }
        if item_type == "message":
            content = item.get("content")
            summary["content_count"] = len(content) if isinstance(content, list) else 0
        if item_type == "reasoning":
            summary["summary_text"] = self._reasoning_summary_preview(item)
        return {key: value for key, value in summary.items() if value not in ("", 0, [])}

    def _reasoning_summary_preview(self, item):
        summary = item.get("summary")
        if not isinstance(summary, list):
            return ""
        parts = []
        for summary_item in summary:
            if isinstance(summary_item, dict) and isinstance(summary_item.get("text"), str):
                parts.append(summary_item["text"])
        preview, _truncated = self._debug_preview("".join(parts), limit=1000)
        return preview
