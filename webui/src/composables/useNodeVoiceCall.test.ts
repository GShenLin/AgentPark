import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useNodeVoiceCall } from './useNodeVoiceCall'

vi.mock('vue', async importOriginal => ({ ...await importOriginal<typeof import('vue')>(), onBeforeUnmount: vi.fn() }))
vi.mock('../api', () => ({ getActiveApiBase: () => 'http://localhost:8788' }))
vi.mock('../voiceApi', () => ({
  describeVoiceCall: vi.fn(async () => 'webrtc'),
  createVoiceCall: vi.fn(async () => ({ transport: 'webrtc', session_id: 's1', model: 'voice', sdp: 'answer', protocol: 'openai-realtime-v1' })),
  voiceRequest: vi.fn(async () => ({ ok: true, record_id: 'voice-s1' })),
  submitVoiceTask: vi.fn(async () => 'r1'),
  getVoiceTask: vi.fn(async () => ({ status: 'completed', text: '已读取文件' })),
  publishVoiceTaskUpdate: vi.fn(async () => ({ status: 'completed', text: '已读取文件' })),
}))

const track = { stop: vi.fn(), enabled: true, onended: null }
const stream = { getTracks: () => [track], getAudioTracks: () => [track] }
class Peer {
  static last: Peer
  iceGatheringState = 'complete'
  localDescription = { sdp: 'offer' }
  dc = { readyState: 'open', send: vi.fn(), close: vi.fn(), onmessage: null as null | ((e: { data: string }) => void) }
  close = vi.fn()
  ontrack?: (event: { track: unknown }) => void
  constructor() { Peer.last = this }
  addTrack() {}
  createDataChannel() { return this.dc }
  async createOffer() { return { sdp: 'offer' } }
  async setLocalDescription() {}
  async setRemoteDescription() {}
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(async () => stream) } })
  vi.stubGlobal('RTCPeerConnection', Peer)
  vi.stubGlobal('Audio', class { pause() {} play() { return Promise.resolve() } })
  vi.stubGlobal('MediaStream', class { tracks: unknown[]; constructor(tracks: unknown[]) { this.tracks = tracks } })
})
afterEach(() => vi.unstubAllGlobals())

it('releases microphone and transport on server denial and preserves the actual error', async () => {
  const voice = useNodeVoiceCall()
  await voice.start('node1', 'graph1')
  expect(voice.active.value).toBe(true)
  expect(voice.connected.value).toBe(false)
  Peer.last.dc.onmessage!({ data: JSON.stringify({ type: 'error', error: { code: 'forbidden', message: 'Voice session access denied.' } }) })
  expect(voice.error.value).toContain('Voice session access denied.')
  expect(voice.active.value).toBe(false)
  expect(voice.stage.value).toBe('通话未接通')
  expect(track.stop).toHaveBeenCalledOnce()
  expect(Peer.last.close).toHaveBeenCalledOnce()
})

it('keeps an established call alive when a second handshake loses its Board response', async () => {
  const { createVoiceCall } = await import('../voiceApi')
  const { BoardRequestInterruptedError } = await import('../portal/boardRequests')
  const first = useNodeVoiceCall(), second = useNodeVoiceCall()
  await first.start('Agent', 'graph'); const originalPeer = Peer.last
  originalPeer.dc.onmessage!({ data: '{"type":"session.created"}' })
  vi.mocked(createVoiceCall).mockRejectedValueOnce(new BoardRequestInterruptedError(false))
  await second.start('Note', 'graph')
  expect(second.stage.value).toBe('通话未接通')
  expect(second.active.value).toBe(false)
  expect(second.error.value).toContain('操作结果待确认')
  expect(first.connected.value).toBe(true)
  expect(originalPeer.close).not.toHaveBeenCalled()
  expect(createVoiceCall).toHaveBeenCalledTimes(2)
  // A user retry creates only the failed node's call, never replays automatically.
  await second.start('Note', 'graph')
  expect(createVoiceCall).toHaveBeenCalledTimes(3)
  Peer.last.dc.onmessage!({ data: '{"type":"session.created"}' })
  expect(second.connected.value).toBe(true)
  expect(first.connected.value).toBe(true)
  first.hangup(); second.hangup()
})

it('reports an interrupted established session instead of leaving the in-call label', async () => {
  const voice = useNodeVoiceCall()
  await voice.start('Agent', 'graph')
  Peer.last.dc.onmessage!({ data: '{"type":"session.created"}' })
  Peer.last.dc.onmessage!({ data: '{"type":"error","error":{"message":"connection lost"}}' })
  expect(voice.stage.value).toBe('通话已中断')
  expect(voice.active.value).toBe(false)
})

it('returns delegated node output while keeping the call active', async () => {
  const voice = useNodeVoiceCall()
  await voice.start('node1', 'graph1')
  Peer.last.dc.onmessage!({ data: '{"type":"session.created"}' })
  expect(voice.connected.value).toBe(true)
  Peer.last.dc.onmessage!({ data: JSON.stringify({ type: 'response.function_call_arguments.done',
    name: 'delegate_to_node', call_id: 'd1', arguments: JSON.stringify({ text: '读取文件' }),
  }) })
  await vi.waitFor(() => expect(Peer.last.dc.send).toHaveBeenCalled())
  const event = JSON.parse(Peer.last.dc.send.mock.calls[0]![0])
  expect(event.type).toBe('conversation.item.create')
  expect(event.item.call_id).toBe('d1')
  expect(event.item.output).toContain('已读取文件')
  expect(voice.active.value).toBe(true)
  voice.hangup()
})

it('still releases the microphone if the hangup notification races a closed channel', async () => {
  const voice = useNodeVoiceCall()
  await voice.start('node1', 'graph1')
  Peer.last.dc.send.mockImplementationOnce(() => { throw new Error('channel closed') })
  voice.hangup()
  expect(track.stop).toHaveBeenCalledOnce()
  expect(Peer.last.close).toHaveBeenCalledOnce()
  expect(voice.active.value).toBe(false)
})

it('routes bridge utterances once through the original node and requests server-owned speech', async () => {
  const { createVoiceCall, submitVoiceTask, publishVoiceTaskUpdate } = await import('../voiceApi')
  vi.mocked(createVoiceCall).mockResolvedValueOnce({ transport: 'webrtc', session_id: 's1', model: 'voice', sdp: 'answer', protocol: 'agentpark-voice-v4' })
  const voice = useNodeVoiceCall()
  await voice.start('original-node', 'graph1')
  Peer.last.dc.onmessage!({ data: '{"type":"ready"}' })
  const event = JSON.stringify({ type: 'delegation', id: 'q1', text: '读取文件' })
  Peer.last.dc.onmessage!({ data: event })
  Peer.last.dc.onmessage!({ data: event })
  await vi.waitFor(() => expect(publishVoiceTaskUpdate).toHaveBeenCalledOnce())
  expect(submitVoiceTask).toHaveBeenCalledOnce()
  expect(submitVoiceTask).toHaveBeenCalledWith(expect.objectContaining({ node: 'original-node' }), 's1', 'q1', '读取文件', expect.any(AbortSignal))
  expect(publishVoiceTaskUpdate).toHaveBeenCalledWith(expect.objectContaining({ node: 'original-node' }), 's1', 'r1', expect.any(AbortSignal))
  expect(Peer.last.dc.send).not.toHaveBeenCalled()
  expect(voice.connected.value).toBe(true)
  voice.hangup()
})

it('preserves an interrupted bridge caption separately from the next answer', async () => {
  const { createVoiceCall, voiceRequest } = await import('../voiceApi')
  vi.mocked(createVoiceCall).mockResolvedValueOnce({ transport: 'webrtc', session_id: 's1', model: 'voice', sdp: 'answer', protocol: 'agentpark-voice-v4' })
  const voice = useNodeVoiceCall()
  await voice.start('node1', 'graph1')
  for (const event of [
    { type: 'transcript', role: 'assistant', text: '尚未播完', done: false, replace: true },
    { type: 'interrupted' },
    { type: 'transcript', role: 'assistant', text: '下一轮回答', done: true, replace: true },
  ]) Peer.last.dc.onmessage!({ data: JSON.stringify(event) })
  voice.hangup()
  await vi.waitFor(() => expect(voice.recordSaving.value).toBe(false))
  const request = vi.mocked(voiceRequest).mock.calls.find(([, path]) => path.endsWith('/finish'))!
  expect(JSON.parse(String(request[2]!.body)).lines).toMatchObject([
    { text: '尚未播完', incomplete: true }, { text: '下一轮回答', incomplete: false },
  ])
})

it('publishes acceptance and progress before completion while incoming conversation stays live', async () => {
  const { createVoiceCall, publishVoiceTaskUpdate, submitVoiceTask } = await import('../voiceApi')
  vi.mocked(createVoiceCall).mockResolvedValueOnce({ transport: 'webrtc', session_id: 's1', model: 'voice', sdp: 'answer', protocol: 'agentpark-voice-v4' })
  vi.mocked(publishVoiceTaskUpdate)
    .mockResolvedValueOnce({ status: 'queued', text: '' })
    .mockResolvedValueOnce({ status: 'running', text: '正在执行：read_file' })
    .mockResolvedValueOnce({ status: 'completed', text: '文件内容' })
  const voice = useNodeVoiceCall()
  await voice.start('node', 'graph')
  Peer.last.dc.onmessage!({ data: '{"type":"ready"}' })
  Peer.last.dc.onmessage!({ data: '{"type":"delegation","id":"call","text":"读取文件"}' })
  await vi.waitFor(() => expect(voice.taskStatus.value).toContain('已排队'))
  Peer.last.dc.onmessage!({ data: '{"type":"transcript","role":"assistant","text":"可以继续聊","done":true,"replace":true}' })
  expect(voice.connected.value).toBe(true)
  await vi.waitFor(() => expect(publishVoiceTaskUpdate).toHaveBeenCalledTimes(3), { timeout: 3500 })
  expect(submitVoiceTask).toHaveBeenCalledOnce()
  expect(voice.taskStatus.value).toBe('节点任务已完成')
  voice.hangup()
})

it('keeps independent conference sessions and releases only the node that is hung up', async () => {
  const { createVoiceCall } = await import('../voiceApi')
  const firstTrack = { stop: vi.fn(), enabled: true, onended: null }
  const secondTrack = { stop: vi.fn(), enabled: true, onended: null }
  const firstMedia = { acquire: vi.fn(async () => ({ getAudioTracks: () => [firstTrack], getTracks: () => [firstTrack] }) as unknown as MediaStream), receive: vi.fn(), release: vi.fn() }
  const secondMedia = { acquire: vi.fn(async () => ({ getAudioTracks: () => [secondTrack], getTracks: () => [secondTrack] }) as unknown as MediaStream), receive: vi.fn(), release: vi.fn() }
  const first = useNodeVoiceCall({ media: firstMedia })
  const second = useNodeVoiceCall({ media: secondMedia })
  await first.start('a', 'graph'); const firstPeer = Peer.last
  await second.start('b', 'graph'); const secondPeer = Peer.last
  firstPeer.dc.onmessage!({ data: '{"type":"session.created"}' })
  secondPeer.dc.onmessage!({ data: '{"type":"session.created"}' })
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
  expect(createVoiceCall).toHaveBeenLastCalledWith(expect.objectContaining({ node: 'b' }), 'offer', expect.any(AbortSignal))
  first.hangup()
  expect(firstMedia.release).toHaveBeenCalledOnce()
  expect(secondMedia.release).not.toHaveBeenCalled()
  expect(secondTrack.stop).not.toHaveBeenCalled()
  expect(second.connected.value).toBe(true)
  second.hangup()
})

it('starts the remote media renderer muted before routing conference audio', async () => {
  const play = vi.fn(async () => {}), pause = vi.fn()
  const element = { play, pause, muted: false, srcObject: null as unknown }
  vi.stubGlobal('Audio', class { constructor() { return element } })
  const media = { acquire: async () => stream as unknown as MediaStream, receive: vi.fn(), release: vi.fn() }
  const voice = useNodeVoiceCall({ media })
  await voice.start('node', 'graph')
  Peer.last.ontrack!({ track: {} })
  expect(element.muted).toBe(true)
  expect(play).toHaveBeenCalledOnce()
  expect(media.receive).toHaveBeenCalledWith(element.srcObject)
  voice.hangup()
  expect(element.srcObject).toBeNull()
  expect(pause).toHaveBeenCalledOnce()
})

it('saves every turn beyond the caption limit and retains the unfinished last caption', async () => {
  const { voiceRequest } = await import('../voiceApi')
  const voice = useNodeVoiceCall()
  await voice.start('node1', 'graph1')
  Peer.last.dc.onmessage!({ data: '{"type":"session.created"}' })
  for (let i = 0; i < 65; i++) {
    Peer.last.dc.onmessage!({ data: JSON.stringify({ type: i % 2 ? 'response.output_audio_transcript.done' : 'conversation.item.input_audio_transcription.completed',
      transcript: `line-${i}`,
    }) })
  }
  Peer.last.dc.onmessage!({ data: '{"type":"response.output_audio_transcript.delta","delta":"unfinished"}' })
  voice.hangup()
  await vi.waitFor(() => expect(voice.recordSaving.value).toBe(false))
  const request = vi.mocked(voiceRequest).mock.calls.find(([, path]) => path.endsWith('/finish'))!
  expect(request[0]).toEqual({ base: 'http://localhost:8788', node: 'node1', graph: 'graph1' })
  const body = JSON.parse(String(request[2]!.body))
  expect(body.status).toBe('ended')
  expect(body.lines).toHaveLength(66)
  expect(body.lines[0].text).toBe('line-0')
  expect(body.lines[65]).toMatchObject({ text: 'unfinished', incomplete: true })
  expect(voice.recordError.value).toBe('')
  expect(vi.mocked(voiceRequest).mock.calls.some(([, , init]) => init?.method === 'DELETE')).toBe(false)
})

it('retains a failed recording for an explicit retry and preserves its exact content', async () => {
  const { voiceRequest } = await import('../voiceApi')
  vi.mocked(voiceRequest).mockRejectedValueOnce(new Error('network offline'))
  const voice = useNodeVoiceCall()
  await voice.start('node1', 'graph1')
  Peer.last.dc.onmessage!({ data: '{"type":"conversation.item.input_audio_transcription.completed","transcript":"keep me"}' })
  Peer.last.dc.onmessage!({ data: '{"type":"error","error":{"message":"connection lost"}}' })
  await vi.waitFor(() => expect(voice.recordError.value).toContain('network offline'))
  await voice.saveRecord()
  expect(voice.recordError.value).toBe('')
  const attempts = vi.mocked(voiceRequest).mock.calls.filter(([, path]) => path.endsWith('/finish'))
  expect(attempts).toHaveLength(2)
  expect(attempts[0]![2]!.body).toBe(attempts[1]![2]!.body)
  expect(JSON.parse(String(attempts[1]![2]!.body))).toMatchObject({ status: 'error', lines: [{ text: 'keep me' }] })
})
