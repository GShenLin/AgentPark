import json


def _build_openai_chat_agent():
    from src.providers.openai_agent import OpenAIAgent
    from src.tool.base_tool import BaseTool

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://chat.example/v1",
        "model": "chat-model",
        "responsesApi": False,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai-chat"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "hello"}]
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    return agent


def test_openai_responses_api_false_uses_chat_completions():
    agent = _build_openai_chat_agent()
    requests = []

    def fake_post(**kwargs):
        requests.append(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "chat ok"}}]}

    agent._curl_post_json_once = lambda **kwargs: fake_post(**kwargs)

    result = agent.Send(web_search="disabled", thinking="disabled", reasoning_effort="high", stream=False)

    assert result == "chat ok"
    assert requests[0]["url"] == "https://chat.example/v1/chat/completions"
    payload = json.loads(requests[0]["payload_json"])
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert payload["reasoning_effort"] == "high"
    assert "input" not in payload


def test_openai_chat_provider_treats_unsupported_web_search_as_disabled():
    agent = _build_openai_chat_agent()
    requests = []

    def fake_post(**kwargs):
        requests.append(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "chat ok"}}]}

    agent._curl_post_json_once = lambda **kwargs: fake_post(**kwargs)

    assert agent.Send(web_search="enabled", thinking="disabled", stream=False) == "chat ok"
    payload = json.loads(requests[0]["payload_json"])
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert "tools" not in payload
    assert "input" not in payload


def test_openai_chat_provider_treats_unsupported_thinking_as_disabled():
    agent = _build_openai_chat_agent()
    requests = []

    def fake_post(**kwargs):
        requests.append(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "chat ok"}}]}

    agent._curl_post_json_once = lambda **kwargs: fake_post(**kwargs)

    assert agent.Send(web_search="disabled", thinking="enabled", stream=False) == "chat ok"
    payload = json.loads(requests[0]["payload_json"])
    assert "thinking" not in payload
    assert "reasoning" not in payload
