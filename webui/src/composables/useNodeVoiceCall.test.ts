import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useNodeVoiceCall } from './useNodeVoiceCall'

vi.mock('vue', async importOriginal => ({ ...await importOriginal<typeof import('vue')>(), onBeforeUnmount: vi.fn() }))
vi.mock('../api', () => ({ getActiveApiBase: () => 'http://localhost:8788' }))
vi.mock('../voiceApi', () => ({
  createVoiceCall: vi.fn(async () => ({ session_id: 's1', model: 'voice', sdp: 'answer' })),
  voiceRequest: vi.fn(async () => ({ ok: true })),
  submitVoiceTask: vi.fn(async () => 'r1'),
  getVoiceTask: vi.fn(async () => ({ status: 'completed', text: '已读取文件' })),
}))

const track = { stop: vi.fn(), enabled: true, onended: null }
const stream = { getTracks: () => [track], getAudioTracks: () => [track] }
class Peer {
  static last: Peer
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
  expect(voice.error.value).toContain('forbidden: Voice session access denied.')
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
  originalPeer.dc.onmessage!({ data: '{"type":"session.started"}' })
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
  Peer.last.dc.onmessage!({ data: '{"type":"session.started"}' })
  expect(second.connected.value).toBe(true)
  expect(first.connected.value).toBe(true)
  first.hangup(); second.hangup()
})

it('reports an interrupted established session instead of leaving the in-call label', async () => {
  const voice = useNodeVoiceCall()
  await voice.start('Agent', 'graph')
  Peer.last.dc.onmessage!({ data: '{"type":"session.started"}' })
  Peer.last.dc.onmessage!({ data: '{"type":"error","error":{"message":"connection lost"}}' })
  expect(voice.stage.value).toBe('通话已中断')
  expect(voice.active.value).toBe(false)
})

it('returns delegated node output while keeping the call active', async () => {
  const voice = useNodeVoiceCall()
  await voice.start('node1', 'graph1')
  Peer.last.dc.onmessage!({ data: '{"type":"session.started"}' })
  expect(voice.connected.value).toBe(true)
  Peer.last.dc.onmessage!({ data: JSON.stringify({ type: 'delegation.created', item: {
    type: 'delegation', target: 'client', id: 'd1', content: [{ type: 'input_text', text: '读取文件' }],
  } }) })
  await vi.waitFor(() => expect(Peer.last.dc.send).toHaveBeenCalled())
  const event = JSON.parse(Peer.last.dc.send.mock.calls[0]![0])
  expect(event.type).toBe('delegation.context.append')
  expect(event.delegation_item_id).toBe('d1')
  expect(event.content[0].text).toContain('已读取文件')
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

it('keeps independent conference sessions and releases only the node that is hung up', async () => {
  const { createVoiceCall } = await import('../voiceApi')
  const firstTrack = { stop: vi.fn(), enabled: true, onended: null }
  const secondTrack = { stop: vi.fn(), enabled: true, onended: null }
  const firstMedia = { acquire: vi.fn(async () => ({ getAudioTracks: () => [firstTrack], getTracks: () => [firstTrack] }) as unknown as MediaStream), receive: vi.fn(), release: vi.fn() }
  const secondMedia = { acquire: vi.fn(async () => ({ getAudioTracks: () => [secondTrack], getTracks: () => [secondTrack] }) as unknown as MediaStream), receive: vi.fn(), release: vi.fn() }
  const first = useNodeVoiceCall({ conference: true, media: firstMedia })
  const second = useNodeVoiceCall({ conference: true, media: secondMedia })
  await first.start('a', 'graph'); const firstPeer = Peer.last
  await second.start('b', 'graph'); const secondPeer = Peer.last
  firstPeer.dc.onmessage!({ data: '{"type":"session.started"}' })
  secondPeer.dc.onmessage!({ data: '{"type":"session.started"}' })
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
  expect(createVoiceCall).toHaveBeenLastCalledWith(expect.objectContaining({ node: 'b' }), 'offer', expect.any(AbortSignal), true)
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
  const voice = useNodeVoiceCall({ conference: true, media })
  await voice.start('node', 'graph')
  Peer.last.ontrack!({ track: {} })
  expect(element.muted).toBe(true)
  expect(play).toHaveBeenCalledOnce()
  expect(media.receive).toHaveBeenCalledWith(element.srcObject)
  voice.hangup()
  expect(element.srcObject).toBeNull()
  expect(pause).toHaveBeenCalledOnce()
})
