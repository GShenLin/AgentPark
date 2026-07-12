from src.providers.openai_mapping import OpenAIResponsesMapping
from src.tool.tool_call_protocol import from_responses_function_call
from src.tool.tool_call_protocol import from_responses_function_call_parse_failure


class GrokResponsesMapping(OpenAIResponsesMapping):
    """xAI Responses request/response mapping.

    Grok follows the Responses item protocol, but its hosted web-search
    configuration is not the same as OpenAI's location/context-size contract.
    """

    def _build_web_search_tool(self):
        tool = {"type": "web_search"}
        allowed_domains = self._grok_domain_filter("webSearchAllowedDomains")
        excluded_domains = self._grok_domain_filter("webSearchExcludedDomains")
        if allowed_domains and excluded_domains:
            raise ValueError(
                "Grok web search cannot use webSearchAllowedDomains and "
                "webSearchExcludedDomains together."
            )
        if allowed_domains:
            tool["filters"] = {"allowed_domains": allowed_domains}
        elif excluded_domains:
            tool["filters"] = {"excluded_domains": excluded_domains}

        for config_key, payload_key in (
            ("webSearchEnableImageUnderstanding", "enable_image_understanding"),
            ("webSearchEnableImageSearch", "enable_image_search"),
        ):
            value = self.config.get(config_key)
            if value is not None:
                if not isinstance(value, bool):
                    raise ValueError(f"provider.{config_key} must be a boolean.")
                tool[payload_key] = value
        return tool

    def _convert_tool_for_responses(self, tool):
        if not isinstance(tool, dict):
            return None
        tool_type = str(tool.get("type") or "").strip().lower()
        if tool_type in {"web_search", "x_search", "code_interpreter", "file_search"}:
            return dict(tool)
        return super()._convert_tool_for_responses(tool)

    def _grok_domain_filter(self, key: str) -> list[str]:
        value = self.config.get(key)
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"provider.{key} must be an array of domain strings.")
        domains = []
        for item in value:
            domain = str(item or "").strip()
            if not domain:
                raise ValueError(f"provider.{key} must contain non-empty domain strings.")
            if domain not in domains:
                domains.append(domain)
        if len(domains) > 5:
            raise ValueError(f"provider.{key} supports at most 5 domains.")
        return domains

    def _openai_responses_function_call_to_item(self, item):
        if not isinstance(item, dict):
            return None
        try:
            return from_responses_function_call(item, provider="grok_responses")
        except ValueError as exc:
            return from_responses_function_call_parse_failure(
                item,
                provider="grok_responses",
                error=exc,
            )
