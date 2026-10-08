import { describe, expect, it } from 'vitest'
import { voiceFieldChanges, voiceFieldOptions } from './voiceSettingsFields'
import { voiceProtocol } from './voiceProtocol'
import { VoiceTranscript } from './voiceTranscript'
import { createNodeConfigAutoApplyQueue } from '../components/agent-board/nodeConfigAutoApply'

const schema = { voice_provider_id: { catalogs: {
  openai: { models: [{ id: 'codex', label: 'Codex', voices: [{ id: 'cove', label: 'Cove' }] }] },
  doubao: { models: [
    { id: 'o2', label: 'O2.0', voices: [{ id: 'vv', label: 'vv' }, { id: 'xiaohe', label: '小何' }] },
    { id: 'sc2', label: 'SC2.0', voices: [{ id: 'saturn', label: 'SC 音色' }] },
  ] },
} } }

describe('provider voice selections', () => {
  it('switches both dependent fields and persists the selection as one batch', async () => {
    const fields = { provider_id: 'text', model: 'text-model', voice_provider_id: 'openai', voice_model: 'codex', voice: 'cove' }
    const changed = voiceFieldChanges(schema, fields, 'voice_provider_id', 'doubao')
    expect(changed).toEqual({ voice_provider_id: 'doubao', voice_model: 'o2', voice: 'vv' })
    const batches: unknown[] = []
    const queue = createNodeConfigAutoApplyQueue({ persist: async batch => { batches.push(batch) }, onError: () => {} })
    for (const [key, value] of Object.entries(changed)) void queue.enqueue('node', key, value)
    await queue.flush()
    expect(batches).toEqual([{ nodeId: 'node', fields: changed }])
    Object.assign(fields, changed)
    expect(voiceFieldOptions(schema, fields, 'voice_model')?.map(item => item.value)).toEqual(['o2', 'sc2'])
    expect(voiceFieldOptions(schema, fields, 'voice')?.map(item => item.value)).toEqual(['vv', 'xiaohe'])
    Object.assign(fields, voiceFieldChanges(schema, fields, 'voice_model', 'sc2'))
    expect(fields.voice).toBe('saturn')
    expect(voiceFieldOptions(schema, fields, 'voice')?.map(item => item.value)).toEqual(['saturn'])
    expect(fields.model).toBe('text-model')
    expect(fields.provider_id).toBe('text')
    Object.assign(fields, voiceFieldChanges(schema, fields, 'voice_provider_id', 'openai'))
    expect(fields.voice).toBe('cove')
  })

  it('exposes incompatible saved selections without silently rewriting them', () => {
    const fields = { voice_provider_id: 'doubao', voice_model: 'o2', voice: 'cove' }
    expect(voiceFieldOptions(schema, fields, 'voice')?.[0]?.label).toContain('不可用')
    expect(fields.voice).toBe('cove')
  })
})

it('keeps ASR replacements and Codex deltas correct in durable transcripts', () => {
  const transcript = new VoiceTranscript()
  const bridge = voiceProtocol('agentpark-voice-v4')
  for (const text of ['你好', '你好世界', '你好世界。']) {
    const event = bridge.parse(JSON.stringify({ type: 'transcript', role: 'user', text, done: text.endsWith('。'), replace: true }))
    if (event.kind === 'transcript') transcript.add(event)
  }
  expect(transcript.finish('ended').lines).toEqual([expect.objectContaining({ text: '你好世界。', incomplete: false })])
  expect(bridge.resultDelivery).toBe('server')
  expect(() => bridge.parse('{"type":"transcript","text":"bad"}')).toThrow()
  expect(voiceProtocol('openai-realtime-v1').parse('{"type":"session.created"}')).toEqual({ kind: 'ready' })
})
