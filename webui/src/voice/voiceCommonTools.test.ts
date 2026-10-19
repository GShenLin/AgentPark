import { beforeEach, expect, it, vi } from 'vitest'
import { voiceProtocol } from './voiceProtocol'
import { VolcRtcEvents } from './VolcRtcEvents'
import { runVoiceTask } from './voiceTaskRunner'
import { voiceRequest } from '../voiceApi'

vi.mock('../voiceApi', () => ({ voiceRequest: vi.fn() }))
const target = { base: 'https://execution', node: 'GPT1', graph: 'default' }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(voiceRequest).mockResolvedValue({ delivery: 'accepted' }) })

function rtcTool(name: string, args: object) {
  const data = new TextEncoder().encode(JSON.stringify({ tool_calls: [{ id: 'tool', type: 'function', function: { name, arguments: JSON.stringify(args) } }] }))
  const buffer = new ArrayBuffer(data.length + 8)
  new Uint8Array(buffer).set(new TextEncoder().encode('tool'))
  new DataView(buffer).setUint32(4, data.length)
  new Uint8Array(buffer, 8).set(data)
  return new VolcRtcEvents('user', 'bot').parse(buffer)[0]!
}

it.each(['agentpark-voice-v4', 'volcengine-rtc-v1'] as const)('executes the same capture and returns its result for %s', async name => {
  const protocol = voiceProtocol(name)
  const event = name === 'volcengine-rtc-v1' ? rtcTool('capture_execution_screen', { display_id: '' })
    : protocol.parse(JSON.stringify({ type: 'tool.call', id: 'tool', name: 'capture_execution_screen', arguments: '{"display_id":""}' }))
  if (event.kind !== 'screenshot') throw new Error('Missing shared screenshot event')
  const capture = vi.fn().mockResolvedValue('{"frame_id":"frame","delivered":true}')
  await runVoiceTask({ target, session: 'session', protocol, signal: new AbortController().signal, event,
    captureScreen: capture, status: vi.fn(), feedback: vi.fn() })
  expect(capture).toHaveBeenCalledExactlyOnceWith('tool', '')
  expect(voiceRequest).toHaveBeenCalledExactlyOnceWith(target, '/session/tools/tool/result', expect.objectContaining({
    body: JSON.stringify({ status: 'completed', text: '{"frame_id":"frame","delivered":true}', image_frame_id: 'frame' }),
  }))
})

it.each(['agentpark-voice-v4', 'volcengine-rtc-v1'] as const)('returns malformed model input as tool failure without session close: %s', async name => {
  const protocol = voiceProtocol(name)
  const event = name === 'volcengine-rtc-v1' ? rtcTool('capture_execution_screen', { display_id: 42 })
    : protocol.parse(JSON.stringify({ type: 'tool.call', id: 'tool', name: 'capture_execution_screen', arguments: '{"display_id":42}' }))
  if (event.kind !== 'tool-error') throw new Error('Malformed input must be a tool error')
  const capture = vi.fn()
  await runVoiceTask({ target, session: 'session', protocol, signal: new AbortController().signal, event,
    captureScreen: capture, status: vi.fn(), feedback: vi.fn() })
  expect(capture).not.toHaveBeenCalled()
  expect(JSON.parse(vi.mocked(voiceRequest).mock.calls[0]![2]!.body as string).status).toBe('failed')
})

it('reads and edits the draft through the RTC result channel', async () => {
  const protocol = voiceProtocol('volcengine-rtc-v1'), options = { target, session: 'session', protocol,
    signal: new AbortController().signal, status: vi.fn(), feedback: vi.fn() }
  await runVoiceTask({ ...options, event: { kind: 'composer', id: 'read', text: '读草稿' },
    readComposer: () => ({ text: '原文', resources: [] }) })
  const edit = vi.fn().mockReturnValue({ text: '修改后', resources: [] })
  await runVoiceTask({ ...options, event: { kind: 'composer-edit', id: 'edit', expected_text: '原文', text: '修改后' }, editComposer: edit })
  expect(edit).toHaveBeenCalledExactlyOnceWith(target, { expected_text: '原文', text: '修改后' })
  expect(vi.mocked(voiceRequest).mock.calls.map(c => c[1])).toEqual(['/session/tools/read/result', '/session/tools/edit/result'])
})
