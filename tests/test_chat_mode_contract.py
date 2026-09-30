import pytest

from nodes.agent_node_modes import MODE_FIELDS, MODE_LABELS, MODE_ORDER, resolve_input_support_mode
from src.harness.node import HarnessNode
from src.providers.agnes_agent import AgnesAgent
from src.providers.gemini_agent import GeminiAgent
from src.providers.grok_agent import GrokAgent
from src.providers.openai_agent import OpenAIAgent
from src.providers.zhipu_agent import ZhipuAgent


def test_chat_and_image_generation_are_distinct_without_legacy_chat_category():
    assert 'chat' in MODE_ORDER and 'image_generation' in MODE_ORDER
    assert 'imagechat' not in MODE_ORDER
    assert 'imagechat' not in MODE_FIELDS
    assert 'imagechat' not in MODE_LABELS
    assert HarnessNode.support_modes == ('chat',)
    with pytest.raises(ValueError, match='does not declare requested SupportMode'):
        resolve_input_support_mode(['chat'], {'parts': [
            {'type': 'meta', 'meta': {'support_mode': 'imagechat'}},
        ]})


@pytest.mark.parametrize('provider', [OpenAIAgent, AgnesAgent, GeminiAgent, GrokAgent, ZhipuAgent])
def test_retired_chat_mode_is_rejected_instead_of_aliased(provider):
    agent = object.__new__(provider)
    agent._read_provider_config_from_file = lambda: {}
    with pytest.raises(ValueError, match='supports'):
        agent.Send(mode='imagechat')
