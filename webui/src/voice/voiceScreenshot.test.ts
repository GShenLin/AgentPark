import { beforeEach, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { parseVoiceTool } from './voiceTools'
import { useVoiceDesktopTools } from './useVoiceDesktopTools'
import { runVoiceTask } from './voiceTaskRunner'
import { RealtimeDialogue } from './RealtimeDialogue'
import { voiceRequest } from '../voiceApi'

vi.mock('../voiceApi', () => ({ voiceRequest: vi.fn() }))
const target = { base: 'https://execution', node: 'GPT', graph: 'default' }
const receipt = { ok: true, delivered: true, frame_id: 'exec_one', width: 1600, height: 900 }
beforeEach(() => vi.resetAllMocks())

it('routes a real tool event to one capture request and sends only its receipt back', async () => {
  const scope = effectScope(), connected = ref(true)
  const desktop = scope.run(() => useVoiceDesktopTools(() => ({ target, session: 'voice' }), connected))!
  expect(voiceRequest).not.toHaveBeenCalled()
  vi.mocked(voiceRequest).mockResolvedValue(receipt)
  const send = vi.fn(), dialogue = new RealtimeDialogue(send)
  const event = dialogue.parse(JSON.stringify({ type: 'response.function_call_arguments.done',
    name: 'capture_execution_screen', call_id: 'tool', arguments: '{"display_id":""}' }))
  if (event.kind !== 'screenshot') throw new Error('Screenshot tool was not parsed')
  await runVoiceTask({ target, session: 'voice', protocol: { resultDelivery: 'data-channel', dialogue, parse: raw => dialogue.parse(raw) },
    signal: new AbortController().signal, event, captureScreen: desktop.capture, status: vi.fn(), feedback: vi.fn() })
  expect(voiceRequest).toHaveBeenCalledExactlyOnceWith(target, '/voice/screenshot', expect.objectContaining({
    body: JSON.stringify({ request_id: 'tool', display_id: '' }),
  }))
  const output = send.mock.calls.find(([e]) => e.item?.type === 'function_call_output')![0]
  expect(JSON.parse(JSON.parse(output.item.output).text)).toEqual(receipt)
  expect(JSON.stringify(send.mock.calls)).not.toContain('input_image')
  dialogue.close(); scope.stop()
})

it.each([{}, { display_id: 1 }, { display_id: '', enabled: true }])('reports malformed screenshot input as a tool error: %j', args => {
  expect(parseVoiceTool('capture_execution_screen', 'tool', JSON.stringify(args))).toMatchObject({ kind: 'tool-error' })
})

it('draws directly without preparing, polling or enabling, and retains voice on failure', async () => {
  const scope = effectScope(), connected = ref(true)
  const desktop = scope.run(() => useVoiceDesktopTools(() => ({ target, session: 'voice' }), connected))!
  const drawing = { action: 'replace' as const, frame_id: 'exec_one', duration_seconds: 10,
    shapes: [{ kind: 'ellipse' as const, x: .9, y: .9, width: .2, height: .2, color: 'red' as const }] }
  vi.mocked(voiceRequest).mockRejectedValueOnce(new Error('native failed')).mockResolvedValue({ ok: true })
  await expect(desktop.draw(drawing)).rejects.toThrow('native failed')
  expect(connected.value).toBe(true)
  await desktop.draw(drawing)
  expect(desktop.drawn.value).toBe(true)
  expect(vi.mocked(voiceRequest).mock.calls.every(call => call[1] === '/voice/annotations' && call[2]?.body === JSON.stringify(drawing))).toBe(true)
  await desktop.clear()
  expect(desktop.drawn.value).toBe(false)
  scope.stop()
})

it('never reports success without provider delivery acknowledgement', async () => {
  const scope = effectScope()
  const desktop = scope.run(() => useVoiceDesktopTools(() => ({ target, session: 'voice' }), ref(true)))!
  vi.mocked(voiceRequest).mockResolvedValue({ ...receipt, delivered: false })
  await expect(desktop.capture('tool', '')).rejects.toThrow('未确认送达')
  scope.stop()
})
