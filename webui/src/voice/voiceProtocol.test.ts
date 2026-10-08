import { expect, it, vi } from 'vitest'
import { voiceProtocol } from './voiceProtocol'
import { createVoiceCall } from '../voiceApi'
import { requestApiJson } from '../api'

vi.mock('../api', () => ({ requestApiJson: vi.fn() }))

it('accepts the complete node-owned voice event sequence including first speech interruption', () => {
  const parse = voiceProtocol('agentpark-voice-v4').parse
  const events = [
    { type: 'ready' },
    { type: 'interrupted' },
    { type: 'transcript', role: 'user', text: '你好', done: false, replace: true },
    { type: 'transcript', role: 'user', text: '你好', done: true, replace: true },
    { type: 'delegation', id: 'q1', text: '你好' },
    { type: 'task.status', text: '此前任务已结束' },
    { type: 'transcript', role: 'assistant', text: '你好。', done: true, replace: true },
    { type: 'closed' },
  ]
  expect(events.map(event => parse(JSON.stringify(event)).kind)).toEqual([
    'ready', 'interrupted', 'transcript', 'transcript', 'delegation', 'task-status', 'transcript', 'closed',
  ])
})

it('identifies a malformed event without logging its conversation content or ignoring it', () => {
  const parse = voiceProtocol('agentpark-voice-v4').parse
  expect(() => parse('{"type":"transcript","text":"private conversation"}')).toThrow('"transcript"')
  expect(() => parse('{"type":"new.event","text":"private conversation"}')).toThrow('"new.event"')
  try { parse('{"type":"transcript","text":"private conversation"}') }
  catch (error) { expect(String(error)).not.toContain('private conversation') }
})

it('advertises exact protocols on dial and refuses a mismatched answer', async () => {
  vi.mocked(requestApiJson).mockResolvedValueOnce({ transport: 'webrtc', session_id: 's1', sdp: 'answer', model: 'speech', protocol: 'agentpark-voice-v4' })
  const target = { base: 'http://localhost', node: 'Agent', graph: 'default' }
  const signal = new AbortController().signal
  await createVoiceCall(target, 'offer', signal)
  expect(JSON.parse(String(vi.mocked(requestApiJson).mock.calls[0]![2]!.body))).toEqual({
    sdp: 'offer', protocols: ['openai-realtime-v1', 'agentpark-voice-v4', 'volcengine-rtc-v1'],
  })
  vi.mocked(requestApiJson).mockResolvedValueOnce({ transport: 'webrtc', session_id: 's1', sdp: 'answer', model: 'speech', protocol: 'agentpark-voice-v1' })
  await expect(createVoiceCall(target, 'offer', signal)).rejects.toThrow('版本与服务不一致')
})
