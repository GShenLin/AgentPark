import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { VolcRtcConnection } from './VolcRtcConnection'
import { controlRtcCall } from '../voiceApi'
import VERTC from '@volcengine/rtc'

const state = vi.hoisted(() => ({ listeners: new Map<string, (e: any) => void>(), engine: {} as any }))
vi.mock('../voiceApi', () => ({ controlRtcCall: vi.fn(async () => {}) }))
vi.mock('@volcengine/rtc', () => ({
  default: { createEngine: vi.fn(() => state.engine), destroyEngine: vi.fn(), events: {
    onError: 'error', onConnectionStateChanged: 'connection', onUserLeave: 'leave', onUserPublishStream: 'publish',
    onRoomBinaryMessageReceived: 'binary', onLocalStreamStats: 'stats',
  } },
  AudioSourceType: { AUDIO_SOURCE_TYPE_EXTERNAL: 0 }, VideoSourceType: { VIDEO_SOURCE_TYPE_EXTERNAL: 0 },
  StreamIndex: { STREAM_INDEX_MAIN: 0, STREAM_INDEX_SCREEN: 1 }, MediaType: { AUDIO: 1, VIDEO: 2 },
  RoomProfileType: { chat: 1 }, RTCAutoPlayPolicy: { PLAY_MANUALLY: 2 }, ConnectionState: { CONNECTION_STATE_LOST: 6 },
}))
const info = { transport: 'volcengine-rtc' as const, app_id: 'app', room_id: 'room', user_id: 'user', bot_id: 'bot', token: 'scoped-token' }
const target = { base: '', node: 'original', graph: 'default' }
const callbacks = () => ({ event: vi.fn(), audio: vi.fn(), error: vi.fn() })
beforeEach(() => {
  vi.clearAllMocks(); state.listeners.clear()
  state.engine = { on: (name: string, handler: (e: any) => void) => state.listeners.set(name, handler),
    getRemoteStreamTrack: vi.fn(() => ({ kind: 'audio' })) }
  for (const name of ['setAudioSourceType', 'setExternalAudioTrack', 'joinRoom', 'publishStream', 'subscribeStream',
    'setScreenEncoderConfig', 'setVideoSourceType', 'setExternalVideoTrack', 'publishScreen', 'unpublishScreen', 'leaveRoom']) {
    state.engine[name] = vi.fn(async () => {})
  }
  vi.stubGlobal('MediaStream', class { tracks: unknown[]; constructor(tracks: unknown[]) { this.tracks = tracks } })
})
afterEach(() => vi.unstubAllGlobals())
const mic = { getAudioTracks: () => [{ kind: 'audio' }] } as unknown as MediaStream

it('reports malformed application messages without closing the RTC audio session', async () => {
  const events = callbacks(), rtc = new VolcRtcConnection(target, 'lease', info, new AbortController().signal, events)
  await rtc.connect(mic)
  state.listeners.get('binary')!({ userId: 'bot', message: new ArrayBuffer(2) })
  expect(events.event).toHaveBeenCalledWith({ kind: 'warning', text: expect.stringContaining('消息头不完整') })
  expect(events.error).not.toHaveBeenCalled()
  expect(state.engine.leaveRoom).not.toHaveBeenCalled()
  await rtc.close()
})

it('joins before activating and requires AI audio subscription before reporting connected', async () => {
  const events = callbacks(), rtc = new VolcRtcConnection(target, 'lease', info, new AbortController().signal, events)
  await rtc.connect(mic)
  expect(state.engine.joinRoom).toHaveBeenCalledWith('scoped-token', 'room', { userId: 'user' }, expect.objectContaining({ isAutoPublish: false }))
  expect(controlRtcCall).toHaveBeenCalledWith(target, 'lease', { action: 'activate' }, expect.any(AbortSignal))
  expect(events.event).not.toHaveBeenCalled()
  state.listeners.get('publish')!({ userId: 'stranger', mediaType: 1 })
  expect(state.engine.subscribeStream).not.toHaveBeenCalled()
  state.listeners.get('publish')!({ userId: 'bot', mediaType: 1 })
  await vi.waitFor(() => expect(events.event).toHaveBeenCalledWith({ kind: 'ready' }))
  expect(events.audio).toHaveBeenCalledOnce()
  await rtc.close()
})

it('waits for a late join on hangup without ever starting the cloud AI', async () => {
  let joined!: () => void
  state.engine.joinRoom.mockImplementation(() => new Promise<void>(resolve => { joined = resolve }))
  const rtc = new VolcRtcConnection(target, 'lease', info, new AbortController().signal, callbacks())
  const connecting = rtc.connect(mic)
  const rejected = expect(connecting).rejects.toThrow('已经结束')
  await vi.waitFor(() => expect(state.engine.joinRoom).toHaveBeenCalledOnce())
  const closing = rtc.close(); joined(); await rejected; await closing
  expect(controlRtcCall).not.toHaveBeenCalled()
  expect(state.engine.leaveRoom).toHaveBeenCalledOnce(); expect(VERTC.destroyEngine).toHaveBeenCalledOnce()
})
