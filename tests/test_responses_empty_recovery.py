"""An empty reply must not erase context or renew its retry budget via a tool."""
import json

from src.providers.openai_agent import OpenAIAgent
from src.tool.base_tool import BaseTool
from src.tool.tool_call_protocol import ToolCallExecution


def run_sequence(responses):
    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        'apiKey': 'test', 'baseUrl': 'https://api.openai.test/v1', 'model': 'gpt-test',
        'responsesApi': True, 'maxRetries': 0, 'retryDelaySec': 0,
        'responsesReplayReasoningItems': False, 'toolResultSubmissionMaxChars': 50000,
        'toolContextCompactionEnabled': False,
    }
    agent.provider_name = 'openai'
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.Message = lambda role, content, persist=True, **kw: agent.messages.append(
        {'role': role, 'content': content, **kw})
    payloads = []

    def respond(**kwargs):
        payloads.append(json.loads(kwargs['payload_json']))
        assert len(payloads) <= len(responses), 'recovery loop exceeded its explicit retry budget'
        return responses[len(payloads)-1]

    agent._stream_responses_with_retry = respond
    agent._execute_tool_call_envelopes_parallel = lambda calls: [ToolCallExecution(
        func_name=call.name, call_id=call.call_id,
        cleaned_result={'assigned_tasks': [], 'revision': 7}, images=()) for call in calls]
    result = agent._send_via_responses(
        messages=[{'role': 'user', 'content': 'Read once. If nothing needs work, finish with a short final sentence.'}],
        active_tools=[], run_tools=True, stream_handler=lambda *_: None)
    return result, payloads


def empty(index):
    return {'id': f'empty-{index}', 'output': []}


def read_board():
    return {'id': 'board', 'output': [{'type': 'function_call', 'id': 'fc-board',
        'call_id': 'call-board', 'name': 'group_board', 'arguments': '{}'}]}


def test_empty_tool_empty_is_bounded_even_when_a_tool_intervenes():
    result, payloads = run_sequence([empty(1), read_board(), empty(2)])
    assert result.startswith('Error: EmptyMessage:')
    assert len(payloads) == 3


def test_recovery_keeps_original_request_and_tool_output_pair():
    final = {'id': 'final', 'output': [{'type': 'message',
        'content': [{'type': 'output_text', 'text': 'No actionable work; waiting for new updates.'}]}]}
    result, payloads = run_sequence([read_board(), empty(1), final])
    assert result == 'No actionable work; waiting for new updates.'
    recovery = payloads[2]['input']
    assert any('Read once.' in str(item.get('content')) for item in recovery)
    assert any(item.get('type') == 'function_call' and item.get('call_id') == 'call-board' for item in recovery)
    assert any(item.get('type') == 'function_call_output' and item.get('call_id') == 'call-board' for item in recovery)
    assert recovery[-1]['content'][0]['text'].startswith('Error: EmptyMessage\n')
