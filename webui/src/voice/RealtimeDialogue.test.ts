import { expect, it, vi } from 'vitest'
import { RealtimeDialogue } from './RealtimeDialogue'

function setup() {
  const send = vi.fn(), dialogue = new RealtimeDialogue(send, () => 20000)
  const event = (data: object) => dialogue.parse(JSON.stringify(data))
  const task = (id = 'call') => event({ type: 'response.function_call_arguments.done', name: 'delegate_to_node', call_id: id, arguments: '{"text":"read file"}' })
  return { send, dialogue, event, task }
}

it('acknowledges submission without holding the tool open and speaks completion after mid-task chat', () => {
  const { send, dialogue, event, task } = setup()
  event({ type: 'response.created' }); task()
  dialogue.taskUpdate('call', { status: 'queued', text: '' })
  expect(send).toHaveBeenCalledTimes(1)
  expect(send.mock.calls[0]![0].item).toMatchObject({ type: 'function_call_output', call_id: 'call' })
  event({ type: 'response.done', response: { status: 'completed' } }); dialogue.flush()
  expect(send.mock.calls[1]![0].type).toBe('response.create')
  event({ type: 'response.created' }); event({ type: 'output_audio_buffer.started' })
  dialogue.taskUpdate('call', { status: 'running', text: 'reading file' })
  dialogue.taskUpdate('call', { status: 'completed', text: 'actual result' })
  event({ type: 'response.done', response: { status: 'completed' } }); dialogue.flush()
  expect(send).toHaveBeenCalledTimes(2) // Audio still playing, don't overlap.
  event({ type: 'input_audio_buffer.speech_started' }); event({ type: 'output_audio_buffer.cleared' }); dialogue.flush()
  expect(send).toHaveBeenCalledTimes(2)
  event({ type: 'input_audio_buffer.speech_stopped' }); dialogue.flush()
  expect(send.mock.calls[2]![0].item.content[0].text).toContain('actual result')
  expect(send.mock.calls[2]![0].item.content[0].text).not.toContain('reading file')
  expect(send.mock.calls[3]![0].type).toBe('response.create')
  dialogue.close(); dialogue.taskUpdate('call', { status: 'failed', text: 'late' }); dialogue.flush()
  expect(send).toHaveBeenCalledTimes(4)
})

it('waits for all tools in a batch and never submits duplicate tool outputs', () => {
  const { send, dialogue, task } = setup(); task('one'); task('two')
  dialogue.taskUpdate('one', { status: 'running', text: '' }); dialogue.flush()
  expect(send).toHaveBeenCalledTimes(1)
  dialogue.taskUpdate('two', { status: 'running', text: '' })
  expect(send.mock.calls[2]![0].type).toBe('response.create')
  dialogue.taskUpdate('one', { status: 'completed', text: 'done' })
  expect(send.mock.calls.filter(([e]) => e.item?.type === 'function_call_output')).toHaveLength(2)
})

it('rejects malformed tools and surfaces server failures', () => {
  const { event, dialogue } = setup()
  expect(event({ type: 'response.function_call_arguments.done', name: 'bad', call_id: 'bad', arguments: '{}' })).toMatchObject({ kind: 'tool-error', text: expect.stringContaining('未注册') })
  expect(() => dialogue.taskUpdate('unknown', { status: 'queued', text: '' })).toThrow('缺少')
  expect(event({ type: 'response.done', response: { status: 'failed', status_details: { error: { message: 'quota' } } } })).toEqual({ kind: 'warning', text: expect.stringContaining('quota') })
})
