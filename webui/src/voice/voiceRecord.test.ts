import { createSSRApp, ref } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { describe, expect, it, vi } from 'vitest'
import type { MessageEnvelope } from '../api'
import { VoiceTranscript } from './voiceTranscript'
import { voiceRecordData, type VoiceRecord } from './voiceRecord'
import { useMemoryTurnEntries } from '../components/memoryFeedTools'
import { extractMemoryMessageText } from '../components/memoryMessageText'
vi.mock('../components/MemoryFileDiffDialog.vue', () => ({ default: { render: () => null } }))
vi.mock('../components/ImageLightbox.vue', () => ({ default: { render: () => null } }))
import MemoryMessageParts from '../components/MemoryMessageParts.vue'
import MobileMessageText from '../mobile/MobileMessageText.vue'

const record: VoiceRecord = {
  kind: 'voice_call', session_id: 's1', started_at: '2026-10-06 10:00:00', ended_at: '2026-10-06 10:01:05',
  status: 'ended', duration_ms: 65000,
  lines: [{ role: 'user', text: 'question', offset_ms: 1000, incomplete: false },
    { role: 'assistant', text: 'answer', offset_ms: 2000, incomplete: true }],
}
const message: MessageEnvelope = { id: 'voice-s1', role: 'voice', created_at: record.ended_at,
  parts: [{ type: 'structured', data: record }] }

describe('persistent voice history', () => {
  it('replaces deltas with the final transcript while preserving interleaved arrival order', () => {
    const transcript = new VoiceTranscript()
    transcript.add({ kind: 'transcript', role: 'user', text: 'que', done: false })
    transcript.add({ kind: 'transcript', role: 'assistant', text: 'ans', done: false })
    transcript.add({ kind: 'transcript', role: 'user', text: 'question', done: true })
    transcript.add({ kind: 'transcript', role: 'assistant', text: 'wer', done: false })
    const snapshot = transcript.finish('ended')
    expect(snapshot.lines.map(line => [line.role, line.text, line.incomplete])).toEqual([
      ['user', 'question', false], ['assistant', 'answer', true],
    ])
    transcript.add({ kind: 'transcript', role: 'assistant', text: 'answer!', done: true })
    expect(snapshot.lines[1]?.text).toBe('answer')
  })

  it('keeps a call as a standalone entry while a delegated task completes', () => {
    const user: MessageEnvelope = { id: 'u1', role: 'user', parts: [{ type: 'text', text: 'task' }], created_at: '' }
    const assistant: MessageEnvelope = { ...user, id: 'a1', role: 'assistant' }
    const entries = useMemoryTurnEntries(ref([user, message, assistant])).value
    expect(entries).toHaveLength(2)
    expect(entries[0]).toMatchObject({ type: 'turn', progressMessages: [], finalResponse: assistant, finalMessages: [] })
    expect(entries[1]).toMatchObject({ type: 'message', message })
  })

  it('renders the collapsed record entry on desktop and mobile', async () => {
    for (const component of [MemoryMessageParts, MobileMessageText]) {
      const html = await renderToString(createSSRApp(component, { message, markdownPreview: true }))
      expect(html).toContain('语音记录')
      expect(html).toContain('1:05')
      expect(html).toContain('2 条对话')
      const detailsTag = html.match(/<details\b[^>]*>/)?.[0]
      expect(detailsTag).toContain('class="voice-record"')
      expect(detailsTag).not.toMatch(/\bopen(?:\s|=|>)/)
      expect(html).not.toContain('voice-record-content')
      expect(html).not.toContain('feed-structured')
      expect(html).not.toContain('bubble-structured')
    }
  })

  it('exports all transcript lines as readable text and validates the record contract', () => {
    expect(voiceRecordData(message.parts[0])).toEqual(record)
    expect(voiceRecordData({ type: 'structured', data: { ...record, lines: [{ role: 'system' }] } })).toBeNull()
    expect(extractMemoryMessageText(message)).toContain('输入语音：question')
    expect(extractMemoryMessageText(message)).toContain('节点（未完成）：answer')
  })
})
