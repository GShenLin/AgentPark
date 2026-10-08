import type { VoiceFinish, VoiceTranscriptLine } from './voiceTranscript'

export type VoiceRecord = VoiceFinish & {
  kind: 'voice_call'; session_id: string; started_at: string; ended_at: string
}

export function voiceRecordData(part: unknown): VoiceRecord | null {
  if (!part || typeof part !== 'object' || !('type' in part) || part.type !== 'structured' || !('data' in part)) return null
  const data = part.data as Partial<VoiceRecord> | null
  if (!data || data.kind !== 'voice_call' || typeof data.session_id !== 'string'
    || typeof data.started_at !== 'string' || typeof data.ended_at !== 'string'
    || !['ended', 'error'].includes(String(data.status)) || typeof data.duration_ms !== 'number'
    || !Array.isArray(data.lines) || !data.lines.every((line: VoiceTranscriptLine) => line
      && ['user', 'assistant'].includes(line.role) && typeof line.text === 'string'
      && typeof line.offset_ms === 'number' && typeof line.incomplete === 'boolean')) return null
  return data as VoiceRecord
}

export function voiceRecordText(record: VoiceRecord): string {
  return [`语音记录 · ${record.started_at} — ${record.ended_at}`,
    ...record.lines.map(line => `${line.role === 'user' ? '输入语音' : '节点'}${line.incomplete ? '（未完成）' : ''}：${line.text}`),
  ].join('\n\n')
}

export function voiceDuration(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}
