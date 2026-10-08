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

it('streams during responses, bounds in-flight frames, retains temporal context and cleans up on stop', () => {
  const { send, dialogue, event } = setup()
  event({ type: 'response.created' }); event({ type: 'output_audio_buffer.started' })
  const ids: string[] = []
  for (let i = 0; i < 30; i++) {
    expect(dialogue.screenFrame(`data:image/jpeg;base64,${i}`)).toBe(true)
    ids.push(send.mock.calls[send.mock.calls.length - 1]![0].item.id)
  }
  expect(dialogue.screenFrame('data:image/jpeg;base64,blocked')).toBe(false)
  for (const id of ids) event({ type: 'conversation.item.added', item: { id } })
  for (let i = 30; i < 31; i++) {
    expect(dialogue.screenFrame(`data:image/jpeg;base64,${i}`)).toBe(true)
    const id = send.mock.calls[send.mock.calls.length - 1]![0].item.id; ids.push(id)
    event({ type: 'conversation.item.added', item: { id } })
    event({ type: 'conversation.item.created', item: { id } }) // Duplicate acknowledgement.
  }
  const deletes = () => send.mock.calls.filter(([e]) => e.type === 'conversation.item.delete').map(([e]) => e.item_id)
  expect(deletes()).toEqual(ids.slice(0, -10))
  expect(send.mock.calls[0]![0].item.content[0].text).toContain('1970-01-01T00:00:20.000Z')
  // Stop also cleans up unacknowledged frames; late acknowledgements are harmless.
  dialogue.screenFrame('data:image/jpeg;base64,pending')
  const pending = send.mock.calls[send.mock.calls.length - 1]![0].item.id
  dialogue.screenStopped()
  expect(deletes()).toEqual([...ids, pending])
  event({ type: 'conversation.item.added', item: { id: pending } })
  expect(deletes()).toEqual([...ids, pending])
  expect(send.mock.calls.filter(([e]) => e.type === 'response.create')).toHaveLength(0)
})

it('reports a missing frame acknowledgement instead of silently freezing the screen', () => {
  let now = 0
  const dialogue = new RealtimeDialogue(vi.fn(), () => now)
  dialogue.screenFrame('data:image/jpeg;base64,one'); now = 10000
  expect(() => dialogue.screenFrame('data:image/jpeg;base64,two')).toThrow('确认超时')
  dialogue.screenStopped()
  expect(dialogue.screenFrame('data:image/jpeg;base64,retry')).toBe(true)
})

it('rejects malformed tools and surfaces server failures', () => {
  const { event, dialogue } = setup()
  expect(() => event({ type: 'response.function_call_arguments.done', name: 'bad' })).toThrow('未注册')
  expect(() => dialogue.taskUpdate('unknown', { status: 'queued', text: '' })).toThrow('缺少')
  expect(event({ type: 'response.done', response: { status: 'failed', status_details: { error: { message: 'quota' } } } })).toEqual({ kind: 'error', text: 'quota' })
})
