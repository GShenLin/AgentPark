import json
import pytest
from src.cli_provider_runtime.contracts import CanonicalResult, CanonicalToolCall
from src.cli_provider_runtime.responses_emitter import ResponsesEmitter
from src.cli_provider_runtime.responses_passthrough import ResponsesPassthrough, ResponsesToolIdentity
from src.cli_provider_runtime.chat_conversion import chat_request_to_canonical
from src.cli_provider_runtime.provider_adapter import provider_protocol


def test_stream_lifecycle_matches_responses_contract():
    emitter = ResponsesEmitter('resp-test', 'model')
    chunks = [emitter.created(), *emitter.reasoning('Plan'), *emitter.text('Hello'), *emitter.text(' world')]
    result = CanonicalResult(response_id='resp-test', text='Hello world', tool_calls=[
        CanonicalToolCall(call_id='call-1', name='read_file', arguments='{"path":"proof.txt"}'),
        CanonicalToolCall(call_id='call-2', name='exec', arguments='read proof', kind='custom')])
    chunks.extend(emitter.completed(result))
    events = [json.loads(c.decode().split('data: ', 1)[1]) for c in chunks]
    assert [e['sequence_number'] for e in events] == list(range(len(events)))
    added = {e['item']['id']: e['output_index'] for e in events if e['type'] == 'response.output_item.added'}
    done = [e['item'] for e in events if e['type'] == 'response.output_item.done']
    assert len(added) == len(done) == 4
    for e in events:
        if 'item_id' in e:
            assert e['output_index'] == added[e['item_id']]
        if e['type'] == 'response.output_text.delta':
            assert e['content_index'] == 0
    assert events[-1]['response']['output'] == done
    assert done[1]['content'][0]['text'] == 'Hello world'
    assert done[2]['call_id'] == 'call-1'
    assert done[3]['input'] == 'read proof'


def test_response_echoed_schema_and_user_data_are_not_tool_calls():
    schema = {'type': 'object', 'properties': {'type': {'type': 'string'},
        'example': {'type': 'function_call', 'name': 'wire', 'arguments': '{"input":"unchanged"}'}}}
    value = {'tools': [{'parameters': schema}], 'output': [
        {'type': 'function_call', 'name': 'wire', 'arguments': '{"input":"code"}', 'call_id': 'c'}]}
    result = ResponsesPassthrough.transform_response(value, {'wire': ResponsesToolIdentity('functions', 'exec', 'custom')})
    assert result['tools'] == value['tools']
    assert result['output'][0]['type'] == 'custom_tool_call'
    assert result['output'][0]['input'] == 'code'


def test_tool_search_keeps_object_arguments_in_added_and_done_events():
    emitter = ResponsesEmitter('resp-search', 'model')
    result = CanonicalResult(response_id='resp-search', tool_calls=[
        CanonicalToolCall(call_id='search-1', name='search', kind='tool_search',
                          arguments='{"query":"read file"}')])
    events = [json.loads(c.decode().split('data: ', 1)[1]) for c in emitter.completed(result)]
    assert events[0]['item']['arguments'] == {'query': 'read file'}
    assert events[1]['item']['arguments'] == {'query': 'read file'}
    assert events[0]['item']['status'] == 'in_progress'
    assert events[1]['item']['status'] == 'completed'
    assert events[0]['item']['id'] == events[1]['item']['id']


def test_forced_chat_tool_choice_is_an_object():
    request = chat_request_to_canonical({'messages': [{'role': 'user', 'content': 'Read'}],
        'tool_choice': {'type': 'function', 'function': {'name': 'read_file'}}}, model='m')
    assert request.tool_choice == {'type': 'function', 'name': 'read_file'}


@pytest.mark.parametrize('kind', ['openai', 'deepseek', 'kimi', 'grok', 'zhipu', 'doubao', 'agnes'])
def test_all_openai_compatible_provider_types_have_a_harness_route(kind):
    assert provider_protocol({'type': kind}) == 'openai_chat'
    assert provider_protocol({'type': kind, 'responsesApi': True}) == 'responses'
