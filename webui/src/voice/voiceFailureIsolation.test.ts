import { expect, it, vi } from 'vitest'
import { RealtimeDialogue } from './RealtimeDialogue'

function fixture() {
  const send = vi.fn(), dialogue = new RealtimeDialogue(send)
  const event = (value: object) => dialogue.parse(JSON.stringify(value))
  return { send, dialogue, event }
}

it('treats a server-side image rejection as a warning while audio remains usable', () => {
  const h = fixture()
  expect(h.event({ type: 'error', error: { event_id: 'exec_screen_create_exec_123', message: 'image refused' } }))
    .toMatchObject({ kind: 'warning', text: expect.stringContaining('image refused') })
  expect(h.event({ type: 'response.output_audio_transcript.done', transcript: '继续通话' }))
    .toMatchObject({ kind: 'transcript', text: '继续通话' })
})



it('rejects a failed context delivery without claiming acknowledgement or ending the call', async () => {
  const h = fixture()
  const delivery = h.dialogue.contextMessage({ id: 'm1', role: 'assistant', parts: [{ type: 'text', text: 'answer' }] })
  const rejected = expect(delivery).rejects.toThrow('context refused')
  const request = h.send.mock.calls[0]![0]
  expect(h.event({ type: 'error', error: { event_id: request.event_id, message: 'context refused' } }))
    .toMatchObject({ kind: 'warning', text: expect.stringContaining('context refused') })
  await rejected
  expect(h.event({ type: 'response.output_audio_transcript.done', transcript: 'still connected' })).toMatchObject({ kind: 'transcript' })
  h.dialogue.close()
})


it('releases the response request state after provider rejection so the next tool can respond', () => {
  const h = fixture()
  const tool = (id: string) => h.event({ type: 'response.function_call_arguments.done', name: 'read_composer_input', call_id: id, arguments: '{"text":"read"}' })
  tool('first'); h.dialogue.taskUpdate('first', { status: 'completed', text: 'first' })
  const request = h.send.mock.calls.map(([event]) => event).find(event => event.type === 'response.create')
  expect(h.event({ type: 'error', error: { event_id: request.event_id, message: 'temporarily refused' } })).toMatchObject({ kind: 'warning' })
  tool('next'); h.dialogue.taskUpdate('next', { status: 'completed', text: 'next' })
  expect(h.send.mock.calls.filter(([event]) => event.type === 'response.create')).toHaveLength(2)
  h.dialogue.close()
})
