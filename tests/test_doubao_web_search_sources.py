import json
import pytest


def _build_agent():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.com/v1",
        "model": "doubao-test",
        "maxRetries": 0,
        "retryDelaySec": 0,
    }
    agent.provider_name = "doubao"
    agent.Message = lambda *_args, **_kwargs: None
    return agent


def test_send_via_responses_keeps_web_search_fields_and_no_auto_strip():
    agent = _build_agent()
    payloads = []

    def _fake_post_json_with_retry(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        payloads.append(payload)
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ]
        }

    agent._post_json_with_retry = _fake_post_json_with_retry

    result = agent._send_via_responses(
        messages=[{"role": "user", "content": "today llm news"}],
        active_tools=[
            {
                "type": "web_search",
                "max_keyword": 5,
                "limit": 10,
                "sources": ["toutiao"],
                "user_location": {"country": "CN", "region": "Beijing", "city": "Beijing"},
            }
        ],
        run_tools=False,
        thinking_mode="enabled",
        web_search_mode="enabled",
    )

    assert result == "ok"
    assert len(payloads) == 1
    sent_tool = payloads[0]["tools"][0]
    assert sent_tool.get("type") == "web_search"
    assert sent_tool.get("sources") == ["toutiao"]
    assert isinstance(sent_tool.get("user_location"), dict)
    assert sent_tool["user_location"] == {"country": "CN", "region": "Beijing", "city": "Beijing"}


def test_web_search_requires_explicit_responses_api_support():
    from src.base_tool import BaseTool
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://api.deepseek.com",
        "model": "deepseek-test",
        "maxRetries": 0,
        "retryDelaySec": 0,
        "type": "doubao",
    }
    agent.provider_name = "deepseek_test"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "search"}]
    agent.tools = BaseTool(agent)
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)

    with pytest.raises(ValueError, match="responsesApi=true"):
        agent.Send(run_tools=False, web_search="enabled")
