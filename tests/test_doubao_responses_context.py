import json


def test_doubao_send_uses_responses_api_for_plain_chat_when_enabled():
    from src.tool.base_tool import BaseTool
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.com/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "plain chat"}]
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []

    def _fake_post_json_with_retry(**kwargs):
        assert kwargs["endpoint"] == "responses"
        payload = json.loads(kwargs["payload_json"])
        payloads.append(payload)
        return {
            "id": "resp-plain",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ],
        }

    agent._post_json_with_retry = _fake_post_json_with_retry
    agent._stream_responses_with_retry = _fake_post_json_with_retry
    agent._stream_chat_completions_with_retry = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("responsesApi=true plain chat must not use chat/completions")
    )

    result = agent.Send(
        run_tools=False,
        web_search="disabled",
        thinking="enabled",
        reasoning_effort="high",
        stream=False,
    )

    assert result == "ok"
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning"] == {"effort": "high"}
    assert "messages" not in payload
    assert payload["input"][-1]["role"] == "user"
    assert payload["input"][-1]["content"][0]["text"] == "plain chat"


def test_doubao_responses_rejects_xhigh_reasoning_effort_before_request():
    from src.tool.base_tool import BaseTool
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.com/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "plain chat"}]
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {
            "id": "resp-plain",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
        }

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    import pytest

    with pytest.raises(ValueError, match="reasoning_effort"):
        agent.Send(run_tools=False, web_search="disabled", reasoning_effort="xhigh", stream=False)
    assert payloads == []


def test_doubao_send_uses_config_reasoning_effort_when_node_value_empty():
    from src.tool.base_tool import BaseTool
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.com/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
        "reasoningEffort": "high",
    }
    agent.provider_name = "doubao"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "plain chat"}]
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {
            "id": "resp-plain",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
        }

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent.Send(run_tools=False, web_search="disabled", reasoning_effort="", stream=False) == "ok"
    assert payloads[0]["reasoning"] == {"effort": "high"}


def test_doubao_responses_rejects_unknown_reasoning_effort_before_request():
    import pytest

    from src.tool.base_tool import BaseTool
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.com/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "plain chat"}]
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    agent._post_json_with_retry = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("request should not be sent"))
    agent._stream_responses_with_retry = agent._post_json_with_retry

    with pytest.raises(ValueError, match="reasoning_effort"):
        agent.Send(run_tools=False, web_search="disabled", reasoning_effort="max", stream=False)


def test_doubao_responses_accepts_base_url_that_already_ends_with_responses():
    from src.tool.base_tool import BaseTool
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.com/api/v3/responses",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "plain chat"}]
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    urls = []

    def fake_post(**kwargs):
        urls.append(kwargs["url"])
        return {"id": "resp-plain", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent.Send(run_tools=False, stream=False) == "ok"
    assert urls == ["https://example.com/api/v3/responses"]


def test_doubao_responses_appends_turn_trigger_after_terminal_assistant_context():
    from src.tool.base_tool import BaseTool
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.com/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.system_prompt = None
    agent.messages = []
    agent._agentpark_responses_instruction = "Call the maintenance tool if needed."
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []

    def _fake_post_json_with_retry(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        payloads.append(payload)
        return {
            "id": "resp-maintenance",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ],
        }

    agent._post_json_with_retry = _fake_post_json_with_retry
    agent._stream_responses_with_retry = _fake_post_json_with_retry

    result = agent._send_via_responses(
        messages=[
            {"role": "system", "content": "Keep this as system prompt."},
            {"role": "user", "content": "inspect project"},
            {"role": "assistant", "content": "I inspected it."},
        ],
        active_tools=[],
        run_tools=True,
        stream=False,
    )

    assert result == "ok"
    payload = payloads[0]
    assert payload["instructions"] == "Call the maintenance tool if needed."
    assert any(item.get("role") == "developer" for item in payload["input"])
    assert not any(item.get("role") == "system" for item in payload["input"])
    assert payload["input"][-2]["role"] == "assistant"
    assert payload["input"][-1]["role"] == "user"
    assert payload["input"][-1]["content"][0]["text"].startswith("Continue by following")
    assert "partial" not in payload


def test_doubao_send_keeps_chat_completions_when_responses_api_disabled():
    from src.tool.base_tool import BaseTool
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.com/v1",
        "model": "doubao-test",
        "responsesApi": False,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "plain chat"}]
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []

    def _fake_post_json_with_retry(**kwargs):
        assert kwargs["endpoint"] == "chat/completions"
        payloads.append(json.loads(kwargs["payload_json"]))
        return {"choices": [{"message": {"role": "assistant", "content": "chat ok"}}]}

    agent._post_json_with_retry = _fake_post_json_with_retry
    agent._stream_responses_with_retry = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("responsesApi=false plain chat must not use /responses")
    )

    result = agent.Send(run_tools=False, web_search="disabled", stream=False)

    assert result == "chat ok"
    assert len(payloads) == 1
    assert payloads[0]["messages"] == [{"role": "user", "content": "plain chat"}]


def test_doubao_responses_plain_chat_context_matches_openai_responses_context(tmp_path):
    from types import SimpleNamespace

    from src.providers.agent_runtime_context import AgentRuntimeContext
    from src.providers.agent_runtime_context import bind_agent_runtime_context
    from src.providers.doubao_agent import DouBaoAgent
    from src.providers.openai_agent import OpenAIAgent
    from src.tool.base_tool import BaseTool

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("Use the project rules.\n", encoding="utf-8")

    def build_agent(agent_cls, provider_name, config, memory_dir):
        memory_dir.mkdir()
        agent = agent_cls.__new__(agent_cls)
        agent.config = dict(config)
        agent.provider_name = provider_name
        agent.system_prompt = None
        agent.messages = []
        agent.tools = BaseTool(agent)
        agent.tool_declarations = []
        agent.events = []
        agent.tool_event_callback = agent.events.append
        agent.memory = SimpleNamespace(current_memory_path=str(memory_dir / "memory.md"))
        agent.internal_memory_enabled = False
        bind_agent_runtime_context(
            agent,
            AgentRuntimeContext(
                graph_id="g_context_parity",
                node_id=f"n_{provider_name}",
                node_type_id="agent_node",
                workspace_root=str(workspace),
                shell="powershell",
                responses_instruction="Base instructions.",
            ),
        )
        agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
            {"role": role, "content": content, **kwargs}
        )
        return agent

    openai_agent = build_agent(
        OpenAIAgent,
        "openai",
        {
            "apiKey": "test",
            "baseUrl": "https://api.openai.test/v1",
            "model": "gpt-test",
            "responsesApi": True,
            "responsesReplayReasoningItems": False,
            "maxRetries": 0,
            "retryDelaySec": 0,
            "toolResultSubmissionMaxChars": 50000,
            "toolContextCompactionEnabled": False,
            "toolContextCompactionEveryToolCalls": 1,
        },
        tmp_path / "openai-memory",
    )
    doubao_agent = build_agent(
        DouBaoAgent,
        "doubao",
        {
            "apiKey": "test",
            "baseUrl": "https://example.com/v1",
            "model": "doubao-test",
            "responsesApi": True,
            "maxRetries": 0,
            "retryDelaySec": 0,
            "toolResultSubmissionMaxChars": 50000,
            "toolContextCompactionEnabled": False,
            "toolContextCompactionEveryToolCalls": 1,
        },
        tmp_path / "doubao-memory",
    )
    payloads = {}

    def attach_fake_post(agent, key):
        def fake_post(**kwargs):
            payloads[key] = json.loads(kwargs["payload_json"])
            return {
                "id": f"resp-{key}",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "ok"}],
                    }
                ],
            }

        agent._post_json_with_retry = fake_post
        agent._stream_responses_with_retry = fake_post

    attach_fake_post(openai_agent, "openai")
    attach_fake_post(doubao_agent, "doubao")

    messages = [
        {"role": "system", "content": "System prompt."},
        {"role": "developer", "content": "Operational memory for this node:\n- Keep the shared context."},
        {"role": "user", "content": "do work"},
    ]
    assert openai_agent._send_via_responses(messages=messages, active_tools=[], run_tools=True) == "ok"
    assert doubao_agent._send_via_responses(messages=messages, active_tools=[], run_tools=True) == "ok"

    for payload in payloads.values():
        assert payload["instructions"] == "Base instructions."
        assert not any(item.get("role") == "system" for item in payload["input"])
        assert payload["input"][0]["role"] == "developer"
        developer_texts = [part["text"] for part in payload["input"][0]["content"]]
        assert developer_texts[0].startswith("<permissions instructions>")
        assert developer_texts[1] == "System prompt."
        assert developer_texts[2].startswith("Operational memory for this node:")
        assert payload["input"][1]["role"] == "user"
        user_context_texts = [part["text"] for part in payload["input"][1]["content"]]
        assert user_context_texts[0].startswith("<environment_context>")
        assert str(workspace) in user_context_texts[0]
        assert user_context_texts[1].startswith("# AGENTS.md instructions")
        assert "Use the project rules." in user_context_texts[1]
        assert payload["input"][-1]["role"] == "user"
        assert payload["input"][-1]["content"][0]["text"] == "do work"


def test_doubao_responses_persists_runtime_context_between_sends(tmp_path):
    from types import SimpleNamespace

    from src.providers.agent_runtime_context import AgentRuntimeContext
    from src.providers.agent_runtime_context import bind_agent_runtime_context
    from src.providers.doubao_agent import DouBaoAgent
    from src.tool.base_tool import BaseTool

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("Keep long-running context visible.\n", encoding="utf-8")
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://example.com/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.system_prompt = None
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(memory_dir / "memory.md"))
    bind_agent_runtime_context(
        agent,
        AgentRuntimeContext(
            graph_id="g_doubao_multi_turn",
            node_id="n_doubao_multi_turn",
            node_type_id="agent_node",
            workspace_root=str(workspace),
            shell="powershell",
            responses_instruction="",
        ),
    )
    payloads = []
    responses = iter(
        [
            {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "one"}]}]},
            {"id": "resp-2", "output": [{"type": "message", "content": [{"type": "output_text", "text": "two"}]}]},
        ]
    )

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(messages=[{"role": "user", "content": "first"}], active_tools=[], run_tools=True) == "one"
    agent.events.clear()
    assert agent._send_via_responses(messages=[{"role": "user", "content": "second"}], active_tools=[], run_tools=True) == "two"

    assert (memory_dir / "agent_turn_context.json").is_file()
    assert (memory_dir / "agent_context_history.json").is_file()
    assert len(payloads) == 2
    second = payloads[1]
    assert second["input"][0]["role"] == "developer"
    assert second["input"][0]["content"][0]["text"].startswith("<permissions instructions>")
    assert second["input"][1]["role"] == "user"
    second_context_texts = [part["text"] for part in second["input"][1]["content"]]
    assert second_context_texts[0].startswith("<environment_context>")
    assert second_context_texts[1].startswith("# AGENTS.md instructions")
    assert "Keep long-running context visible." in second_context_texts[1]
    updates = [
        json.loads(event["message"])
        for event in agent.events
        if event.get("type") == "runtime_notice"
        and event.get("stage") == "openai_responses_context_update"
    ]
    assert updates[0]["persistent_context_update_mode"] == "unchanged"
