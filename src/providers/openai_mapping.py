from src.providers.responses_mapping import ResponsesMapping
from src.tool.tool_call_protocol import ensure_json_text
from src.tool.tool_call_protocol import from_responses_function_call_parse_failure
from src.tool.tool_call_protocol import ToolCallEnvelope
from src.tool.tool_call_protocol import ToolCallParseFailure
from src.tool.tool_call_protocol import parse_arguments
from src.providers.server_tool_protocol import extract_responses_server_tool_result


class OpenAIResponsesMapping(ResponsesMapping):
    def _build_web_search_tool(self):
        tool_type = str(self.config.get("webSearchToolType", "web_search") or "").strip()
        tool = {"type": tool_type or "web_search"}

        user_location = self.config.get("webSearchUserLocation")
        if isinstance(user_location, dict):
            safe_location = {
                str(key): value
                for key, value in user_location.items()
                if value is not None and value != ""
            }
            if safe_location:
                tool["user_location"] = safe_location

        context_size = self.config.get("webSearchContextSize")
        context_size_text = str(context_size or "").strip().lower()
        if context_size_text in {"low", "medium", "high"}:
            tool["search_context_size"] = context_size_text

        return tool

    def _convert_tool_for_responses(self, tool):
        if not isinstance(tool, dict):
            return None
        tool_type = str(tool.get("type") or "").strip().lower()
        if tool_type in {"web_search", "web_search_preview"}:
            return dict(tool)
        if tool_type != "function":
            return None
        fn = tool.get("function")
        if not isinstance(fn, dict):
            return None
        name = str(fn.get("name") or "").strip()
        if not name:
            return None
        return {
            "type": "function",
            "name": name,
            "description": str(fn.get("description") or ""),
            "parameters": fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {"type": "object"},
        }

    def _build_responses_tools(self, active_tools, web_search_mode="disabled"):
        tools_out = []
        for tool in active_tools if isinstance(active_tools, list) else []:
            converted = self._convert_tool_for_responses(tool)
            if isinstance(converted, dict):
                tools_out.append(converted)
        if web_search_mode == "enabled":
            has_web_search = any(
                str((item or {}).get("type") or "").strip().lower() in {"web_search", "web_search_preview"}
                for item in tools_out
            )
            if not has_web_search:
                tools_out.append(self._build_web_search_tool())
        return tools_out

    def _build_responses_continuation_input_items(self, result, function_calls):
        output = result.get("output") if isinstance(result, dict) else None
        if not isinstance(output, list):
            return self._build_responses_function_call_input_items(function_calls)

        items = []
        function_call_by_id = {
            call.call_id: call
            for call in function_calls
            if isinstance(call, (ToolCallEnvelope, ToolCallParseFailure)) and str(call.call_id or "").strip()
        }
        seen_function_call_ids = set()
        for item in output:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            if item_type == "reasoning":
                if self._responses_replay_reasoning_items():
                    items.append(dict(item))
                continue
            if item_type == "message":
                # Text emitted beside a function call is user-visible progress,
                # not protocol history for the next model request.
                continue
            if item_type != "function_call":
                continue
            call_id = str(item.get("call_id") or "").strip()
            call = function_call_by_id.get(call_id)
            if call is None:
                continue
            seen_function_call_ids.add(call_id)
            items.extend(self._build_responses_function_call_input_items([call]))

        for call in function_calls if isinstance(function_calls, list) else []:
            if isinstance(call, (ToolCallEnvelope, ToolCallParseFailure)) and call.call_id not in seen_function_call_ids:
                items.extend(self._build_responses_function_call_input_items([call]))
        return items

    def _responses_message_output_to_input_item(self, item):
        if not isinstance(item, dict):
            return None
        content = item.get("content")
        if not isinstance(content, list):
            return None
        return self._message_content_to_responses_item("assistant", content)

    def _responses_replay_reasoning_items(self):
        if "responsesReplayReasoningItems" not in self.config:
            raise ValueError(
                "provider.responsesReplayReasoningItems is required. "
                "Set it explicitly to true or false."
            )
        value = self.config.get("responsesReplayReasoningItems")
        if not isinstance(value, bool):
            raise ValueError("provider.responsesReplayReasoningItems must be a boolean.")
        return value

    def _parse_responses_output_envelopes(self, result):
        text_parts = []
        function_calls = []
        output = result.get("output") if isinstance(result, dict) else None
        if not isinstance(output, list):
            output = []
        for item in output:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            if item_type == "function_call":
                call = self._openai_responses_function_call_to_item(item)
                if call is not None:
                    function_calls.append(call)
                continue
            if item_type != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and str(part.get("type") or "").strip().lower() in {"output_text", "text"}:
                    text = str(part.get("text") or "")
                    if text:
                        text_parts.append(text)
        return "\n".join(text_parts).strip(), function_calls, str(result.get("id") or "").strip() if isinstance(result, dict) else ""

    def _parse_responses_structured_result(self, result):
        return extract_responses_server_tool_result(result)

    def _openai_responses_function_call_to_item(self, item):
        if not isinstance(item, dict):
            return None
        if str(item.get("type") or "").strip().lower() != "function_call":
            return None
        name = str(item.get("name") or "").strip()
        call_id = str(item.get("call_id") or "").strip()
        if not name or not call_id:
            return None
        if call_id.startswith("fc_"):
            raise ValueError(
                "OpenAI Responses function_call.call_id used an output item id. "
                "Expected the function call call_id field, not the function_call item id."
            )
        raw_arguments = item.get("arguments")
        arguments_json = ensure_json_text(raw_arguments if raw_arguments is not None else {})
        try:
            arguments = parse_arguments(arguments_json)
        except ValueError as exc:
            return from_responses_function_call_parse_failure(
                item,
                provider="openai_responses",
                error=exc,
            )
        return ToolCallEnvelope(
            name=name,
            call_id=call_id,
            arguments=arguments,
            arguments_json=arguments_json,
            provider="openai_responses",
            raw=item,
        )
