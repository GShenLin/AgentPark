from src.providers.responses_mapping import ResponsesMapping
from src.tool.tool_call_protocol import from_responses_function_call
from src.tool.tool_call_protocol import from_responses_function_call_parse_failure
from src.tool.tool_call_protocol import to_openai_tool_call


class DoubaoResponsesMapping(ResponsesMapping):
    def _responses_text_part_type(self, _role: str) -> str:
        return "input_text"

    def _responses_include_refusal_parts(self) -> bool:
        return False

    def _responses_tool_message_output(self, *, tool_name: str, call_id: str, content):
        return self._compact_tool_result_for_submission_if_needed(
            tool_name=tool_name,
            call_id=call_id,
            content=content,
        )

    def _build_web_search_tool(self):
        tool = {"type": "web_search"}
        max_keyword = self.config.get("webSearchMaxKeyword", 2)
        limit = self.config.get("webSearchLimit")
        sources = self.config.get("webSearchSources")

        try:
            mk = int(max_keyword)
            if 1 <= mk <= 50:
                tool["max_keyword"] = mk
        except Exception:
            pass
        try:
            lm = int(limit)
            if 1 <= lm <= 50:
                tool["limit"] = lm
        except Exception:
            pass
        if isinstance(sources, list):
            safe_sources = [str(item).strip() for item in sources if str(item or "").strip()]
            if safe_sources:
                tool["sources"] = safe_sources
        return tool

    def _convert_tool_for_responses(self, tool):
        if not isinstance(tool, dict):
            return None
        tool_type = str(tool.get("type") or "").strip().lower()
        if tool_type == "function":
            fn = tool.get("function")
            if isinstance(fn, dict):
                name = str(fn.get("name") or "").strip()
                if not name:
                    return None
                return {
                    "type": "function",
                    "name": name,
                    "description": str(fn.get("description") or ""),
                    "parameters": fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {"type": "object"},
                }
            name = str(tool.get("name") or "").strip()
            if not name:
                return None
            return {
                "type": "function",
                "name": name,
                "description": str(tool.get("description") or ""),
                "parameters": tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {"type": "object"},
            }
        if tool_type == "web_search":
            return {"type": "web_search", **{k: v for k, v in tool.items() if k != "type"}}
        return tool

    def _build_responses_tools(self, active_tools, web_search_mode):
        tools_out = []
        if isinstance(active_tools, list):
            for tool in active_tools:
                converted = self._convert_tool_for_responses(tool)
                if isinstance(converted, dict):
                    tools_out.append(converted)
        if web_search_mode == "enabled":
            has_web_search = any(str((item or {}).get("type") or "").strip().lower() == "web_search" for item in tools_out)
            if not has_web_search:
                tools_out.append(self._build_web_search_tool())
        return tools_out

    def _parse_responses_output(self, result):
        text, tool_calls, response_id = self._parse_responses_output_envelopes(result)
        return text, [to_openai_tool_call(call) for call in tool_calls], response_id

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
                try:
                    call = from_responses_function_call(item, provider="doubao_responses")
                except ValueError as exc:
                    call = from_responses_function_call_parse_failure(
                        item,
                        provider="doubao_responses",
                        error=exc,
                    )
                if call is None:
                    continue
                function_calls.append(call)
                continue

            if item_type != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "").strip().lower()
                if part_type in {"output_text", "text"}:
                    text = str(part.get("text") or "")
                    if text:
                        text_parts.append(text)
                elif part_type == "refusal":
                    refusal = str(part.get("refusal") or part.get("text") or "")
                    if refusal:
                        text_parts.append(refusal)

        text = "\n".join([part for part in text_parts if part]).strip()
        response_id = str(result.get("id") or "").strip() if isinstance(result, dict) else ""
        return text, function_calls, response_id
