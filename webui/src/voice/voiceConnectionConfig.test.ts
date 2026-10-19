import { expect, it, vi } from 'vitest'
import { requestApiJson } from '../api'
import { describeVoiceCall } from '../voiceApi'

vi.mock('../api', () => ({ requestApiJson: vi.fn() }))
const target = { base: '', node: 'GPT1', graph: 'default' }

it('provides TURN credentials to the voice connection separately from Board connectivity', async () => {
  const ice = [{ urls: ['turn:relay.test:3478?transport=tcp'], username: 'short-lived', credential: 'scoped' }]
  vi.mocked(requestApiJson).mockResolvedValue({ transport: 'webrtc', protocol: 'openai-realtime-v4', ice_servers: ice })
  expect(await describeVoiceCall(target, new AbortController().signal)).toEqual({ transport: 'webrtc', iceServers: ice })
})

it('supports explicitly configured direct-only local deployments and separate RTC transport', async () => {
  vi.mocked(requestApiJson).mockResolvedValue({ transport: 'webrtc', protocol: 'openai-realtime-v4', ice_servers: [] })
  expect(await describeVoiceCall(target, new AbortController().signal)).toEqual({ transport: 'webrtc', iceServers: [] })
  vi.mocked(requestApiJson).mockResolvedValue({ transport: 'volcengine-rtc', protocol: 'volcengine-rtc-v1' })
  expect(await describeVoiceCall(target, new AbortController().signal)).toEqual({ transport: 'volcengine-rtc' })
})
