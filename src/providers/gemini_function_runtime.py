from src.providers.tool_call_runtime import ToolCallExecutionMixin
from src.service_host import HostBoundService
from src.tool.tool_call_protocol import from_gemini_function_call


class GeminiFunctionRuntime(ToolCallExecutionMixin, HostBoundService):
    def _convert_tool_to_gemini(self, openai_tool):
        if openai_tool.get("type") == "function":
            func = openai_tool.get("function", {})
            gemini_tool = {
                "name": func.get("name"),
                "description": func.get("description"),
            }
            if "parameters" in func:
                gemini_tool["parameters"] = self._convert_schema_type(func["parameters"])
            return gemini_tool
        return openai_tool

    def _convert_schema_type(self, schema):
        if not isinstance(schema, dict):
            return schema

        new_schema = schema.copy()
        if "type" in new_schema:
            new_schema["type"] = new_schema["type"].upper()
        if "properties" in new_schema:
            new_props = {}
            for key, value in new_schema["properties"].items():
                new_props[key] = self._convert_schema_type(value)
            new_schema["properties"] = new_props
        if "items" in new_schema:
            new_schema["items"] = self._convert_schema_type(new_schema["items"])
        for key in ("oneOf", "anyOf", "allOf"):
            if isinstance(new_schema.get(key), list):
                new_schema[key] = [
                    self._convert_schema_type(item)
                    for item in new_schema[key]
                ]
        return new_schema

    def _execute_function_calls_parallel(self, function_calls):
        if not isinstance(function_calls, list) or not function_calls:
            return []
        envelopes = self._normalize_gemini_function_calls(function_calls)
        return self._execute_tool_call_envelopes_parallel(envelopes)

    def _normalize_gemini_function_calls(self, function_calls):
        envelopes = []
        for item in function_calls if isinstance(function_calls, list) else []:
            call = from_gemini_function_call(item)
            if call is not None:
                envelopes.append(call)
        return envelopes

    def _extract_candidate_calls_and_text(self, parts):
        if not isinstance(parts, list):
            return [], "", False

        function_calls = []
        text_content = ""
        has_text = False
        for part in parts:
            if not isinstance(part, dict):
                continue
            func_call = part.get("functionCall")
            if isinstance(func_call, dict):
                function_calls.append(func_call)
            if "text" in part:
                has_text = True
                text_content += str(part.get("text") or "")
        return function_calls, text_content, has_text

    def _pick_candidate_content(self, candidates, run_tools):
        if not isinstance(candidates, list) or not candidates:
            return None, None

        if run_tools:
            for idx, candidate in enumerate(candidates):
                content = (candidate or {}).get("content") or {}
                parts = content.get("parts")
                function_calls, _, _ = self._extract_candidate_calls_and_text(parts)
                if function_calls:
                    return candidate, idx

        return candidates[0], 0
