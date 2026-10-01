import { describe, expect, it } from 'vitest'
import { delegationResult, parseVoiceEvent, voiceContextChunks } from './codexVoiceProtocol'

describe('Codex OAuth voice protocol', () => {
  it('keeps service denial distinct from an accepted session', () => {
    expect(parseVoiceEvent(JSON.stringify({ type: 'error', error: { code: 'forbidden', message: 'Voice session access denied.' } })))
      .toEqual({ kind: 'error', text: 'forbidden: Voice session access denied.' })
    expect(parseVoiceEvent('{"type":"session.started"}')).toEqual({ kind: 'ready' })
    expect(parseVoiceEvent('{"type":"session.created"}')).toEqual({ kind: 'other' })
  })
  it('extracts only valid client delegations', () => {
    const event = { type: 'delegation.created', item: { type: 'delegation', target: 'client', id: 'd1', content: [{ type: 'input_text', text: '查日志' }] } }
    expect(parseVoiceEvent(JSON.stringify(event))).toEqual({ kind: 'delegation', id: 'd1', text: '查日志' })
    expect(() => parseVoiceEvent(JSON.stringify({ ...event, item: { ...event.item, target: 'unknown' } }))).toThrow()
  })
  it('preserves Chinese and emoji across the upstream byte limit', () => {
    const source = '你好🌍'.repeat(180)
    const chunks = voiceContextChunks(source)
    expect(chunks.join('')).toBe(source)
    expect(chunks.every(chunk => new TextEncoder().encode(chunk).length <= 500)).toBe(true)
    const result = delegationResult('d1', source)
    expect(result.every(item => item.delegation_item_id === 'd1')).toBe(true)
    expect(result.map(item => item.content[0]!.text).join('')).toBe(source)
  })
  it('separates transcript additions from completed turns', () => {
    expect(parseVoiceEvent('{"type":"input_transcript.added","item":{"text":"你好"}}'))
      .toEqual({ kind: 'transcript', role: 'user', text: '你好', done: false })
    expect(parseVoiceEvent('{"type":"turn.done","turn":{"role":"assistant","transcript":"完成"}}'))
      .toEqual({ kind: 'transcript', role: 'assistant', text: '完成', done: true })
  })
})
