import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiHttpError, ApiNetworkError } from '../api'
import { BoardRequestInterruptedError, BoardUnavailableError } from '../portal/boardRequests'
import { getVoiceTask, submitVoiceTask, voiceRequest } from '../voiceApi'
import { RealtimeDialogue } from './RealtimeDialogue'
import { runVoiceTask } from './voiceTaskRunner'
import { syncVoiceContext } from './voiceContextSync'
import { createVoiceComposers } from './voiceComposer'

vi.mock('../voiceApi', () => ({
  getVoiceTask: vi.fn(), publishVoiceTaskUpdate: vi.fn(), submitVoiceTask: vi.fn(), voiceRequest: vi.fn(),
}))
beforeEach(() => { vi.resetAllMocks(); vi.useFakeTimers() })
afterEach(() => vi.useRealTimers())
const target = { base: 'http://node', graph: 'graph', node: 'GPT' }
function harness(name = 'delegate_to_node') {
  const controller = new AbortController(), send = vi.fn(), status = vi.fn(), feedback = vi.fn()
  const dialogue = new RealtimeDialogue(send)
  dialogue.parse(JSON.stringify({ type: 'response.function_call_arguments.done', name, call_id: 'call', arguments: '{"text":"阅读资料"}' }))
  const options = { target, session: 's', signal: controller.signal, status, feedback,
    protocol: { resultDelivery: 'data-channel' as const, dialogue, parse: (raw: string) => dialogue.parse(raw) },
    event: { kind: name === 'delegate_to_node' ? 'delegation' as const : 'composer' as const, id: 'call', text: '阅读资料' },
  }
  return { controller, send, status, feedback, dialogue, options }
}

it('resumes the same task after HTTP and Board outages without submitting it again', async () => {
  const h = harness()
  vi.mocked(submitVoiceTask).mockResolvedValue('request')
  vi.mocked(getVoiceTask).mockRejectedValueOnce(new ApiNetworkError('offline'))
    .mockRejectedValueOnce(new BoardUnavailableError())
    .mockRejectedValueOnce(new BoardRequestInterruptedError(true))
    .mockResolvedValue({ status: 'completed', text: '搜索的实际答案' })
  const run = runVoiceTask(h.options)
  await vi.advanceTimersByTimeAsync(4000); await run
  expect(submitVoiceTask).toHaveBeenCalledOnce()
  expect(getVoiceTask).toHaveBeenCalledTimes(4)
  expect(h.feedback).toHaveBeenCalledWith(expect.stringContaining('恢复'))
  expect(h.send.mock.calls.some(([event]) => event.item?.output?.includes('搜索的实际答案'))).toBe(true)
  h.dialogue.close()
})

it('retries an ambiguous acceptance with exactly the same id and immutable draft', async () => {
  const h = harness('read_composer_input')
  const draft = { text: '原始草稿', resources: [{ uri: '/actual/video.mp4', name: 'video.mp4', kind: 'video' as const, mime: 'video/mp4', source: 'voice_composer' }] }
  const readComposer = vi.fn(() => structuredClone(draft))
  vi.mocked(submitVoiceTask).mockRejectedValueOnce(new BoardRequestInterruptedError(false)).mockResolvedValue('request')
  vi.mocked(getVoiceTask).mockResolvedValue({ status: 'completed', text: '已读取视频画面' })
  const run = runVoiceTask({ ...h.options, readComposer })
  draft.text = '后来编辑'; draft.resources = []
  await vi.advanceTimersByTimeAsync(500); await run
  expect(readComposer).toHaveBeenCalledOnce()
  const calls = vi.mocked(submitVoiceTask).mock.calls
  expect(calls).toHaveLength(2)
  expect(calls[0]).toEqual(calls[1])
  expect(calls[0]![5]!.text).toBe('原始草稿')
  expect(calls[0]![5]!.resources[0]!.kind).toBe('video')
  expect(draft.text).toBe('后来编辑')
  h.dialogue.close()
})

it('reads unsent text without sending a node message or clearing the composer', async () => {
  const h = harness('read_composer_input')
  const snapshot = { text: '这是还没发送的内容', resources: [] }
  await runVoiceTask({ ...h.options, readComposer: () => snapshot })
  expect(submitVoiceTask).not.toHaveBeenCalled()
  expect(h.send.mock.calls[0]![0].item.output).toContain(snapshot.text)
  expect(snapshot.text).toBe('这是还没发送的内容')
  h.dialogue.close()
})

it('does not retry permission/protocol errors or perform work after hangup', async () => {
  const h = harness()
  vi.mocked(submitVoiceTask).mockRejectedValue(new ApiHttpError(403, 'denied'))
  await expect(runVoiceTask(h.options)).rejects.toThrow('403')
  expect(submitVoiceTask).toHaveBeenCalledOnce()
  vi.mocked(submitVoiceTask).mockRejectedValue(new ApiNetworkError('offline'))
  const run = runVoiceTask(h.options).catch(error => error)
  await vi.advanceTimersByTimeAsync(1)
  h.controller.abort(new Error('hangup'))
  expect((await run).message).toBe('hangup')
  await vi.advanceTimersByTimeAsync(60000)
  expect(submitVoiceTask).toHaveBeenCalledTimes(2)
  h.dialogue.close()
})

it('syncs full new chat content after an outage and advances only after provider acknowledgement', async () => {
  const h = harness()
  const message = { id: 'new-answer', role: 'assistant', parts: [{ type: 'text', text: '全文' .repeat(16000) + '最后一句' }] }
  vi.mocked(voiceRequest).mockRejectedValueOnce(new ApiNetworkError('offline'))
    .mockResolvedValueOnce({ cursor: message.id, messages: [message] })
    .mockResolvedValue({ cursor: message.id, messages: [] })
  const run = syncVoiceContext(target, 's', h.dialogue, h.controller.signal, h.status).catch(error => error)
  await vi.advanceTimersByTimeAsync(1500)
  expect(voiceRequest).toHaveBeenCalledTimes(2)
  const sent = h.send.mock.calls.map(([event]) => event).filter(event => event.type === 'conversation.item.create')
  expect(sent).toHaveLength(3)
  expect(sent.map(event => event.item.content[0].text).join('')).toContain('最后一句')
  for (const event of sent) h.dialogue.parse(JSON.stringify({ type: 'conversation.item.added', item: { id: event.item.id } }))
  await vi.advanceTimersByTimeAsync(1000)
  expect(vi.mocked(voiceRequest).mock.calls[2]![1]).toBe('/s/context?after=new-answer')
  expect(h.send.mock.calls.filter(([event]) => event.type === 'conversation.item.create')).toHaveLength(3)
  h.controller.abort(); h.dialogue.close(); await run
})

it('queues task results during an audio network interruption and reconciles missing acknowledgements', async () => {
  const h = harness()
  h.dialogue.transportAvailable(false)
  h.dialogue.taskUpdate('call', { status: 'completed', text: '断网时完成的答案' })
  expect(h.send).not.toHaveBeenCalled()
  h.dialogue.transportAvailable(true); h.dialogue.flush()
  const first = h.send.mock.calls[0]![0]
  expect(first.item.output).toContain('断网时完成的答案')
  await vi.advanceTimersByTimeAsync(11000); h.dialogue.flush()
  expect(h.send.mock.calls.filter(([event]) => event.type === 'conversation.item.create')).toHaveLength(1)
  expect(h.send.mock.calls.some(([event]) => event.type === 'conversation.item.retrieve' && event.item_id === first.item.id)).toBe(true)
  h.dialogue.parse(JSON.stringify({ type: 'conversation.item.retrieved', item: { id: first.item.id } }))
  const count = h.send.mock.calls.length
  await vi.advanceTimersByTimeAsync(11000); h.dialogue.flush()
  expect(h.send.mock.calls).toHaveLength(count)
  h.dialogue.close()
})

it('isolates composer access by device, graph and node, rejects pending uploads, and unregisters closed views', () => {
  const composers = createVoiceComposers()
  let uploading = true
  const attachments = [
    { name: 'picture.png', path: '/picture.png' }, { name: 'clip.mp4', path: '/clip.mp4' },
    { name: 'report.pdf', path: '/report.pdf' }, { name: 'other.bin', path: '/other.bin' },
  ]
  const unregister = composers.register(() => ({ target, text: '文字', attachments, uploading, locked: false }), vi.fn())
  expect(() => composers.read(target)).toThrow('上传')
  uploading = false
  const snapshot = composers.read(target)
  expect(snapshot.resources.map(resource => resource.kind)).toEqual(['image', 'video', 'doc', 'file'])
  snapshot.resources.pop()
  expect(attachments).toHaveLength(4)
  for (const other of [{ ...target, base: 'other' }, { ...target, graph: 'other' }, { ...target, node: 'other' }]) {
    expect(() => composers.read(other)).toThrow('打开')
  }
  unregister()
  expect(() => composers.read(target)).toThrow('打开')
})

it('resends the original item only when the provider explicitly confirms it was not received', async () => {
  const h = harness()
  h.dialogue.taskUpdate('call', { status: 'completed', text: '需要补送的结果' })
  const original = h.send.mock.calls[0]![0].item
  await vi.advanceTimersByTimeAsync(10000); h.dialogue.flush()
  const probe = h.send.mock.calls.find(([event]) => event.type === 'conversation.item.retrieve')![0]
  // Exact code observed from the live GA Realtime service.
  expect(h.dialogue.parse(JSON.stringify({ type: 'error', error: {
    code: 'item_retrieve_invalid_item_id', event_id: probe.event_id, message: 'item does not exist',
  } }))).toEqual({ kind: 'other' })
  h.dialogue.flush()
  const creates = h.send.mock.calls.filter(([event]) => event.type === 'conversation.item.create')
  expect(creates).toHaveLength(2)
  expect(creates[1]![0].item).toEqual(original)
  h.dialogue.parse(JSON.stringify({ type: 'conversation.item.added', item: original }))
  await vi.advanceTimersByTimeAsync(10000); h.dialogue.flush()
  expect(h.send.mock.calls.filter(([event]) => event.type === 'conversation.item.create')).toHaveLength(2)
  h.dialogue.close()
})
