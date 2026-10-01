export type VoiceEvent =
  | { kind: 'ready' }
  | { kind: 'closed' }
  | { kind: 'error'; text: string }
  | { kind: 'transcript'; role: 'user' | 'assistant'; text: string; done: boolean }
  | { kind: 'delegation'; id: string; text: string }
  | { kind: 'other' }

function text(value: unknown, name: string): string {
  if (typeof value !== 'string') throw new Error(`语音协议字段 ${name} 无效。`)
  return value
}

export function parseVoiceEvent(raw: string): VoiceEvent {
  const event = JSON.parse(raw)
  if (!event || typeof event.type !== 'string') throw new Error('语音服务器返回了无效事件。')
  switch (event.type) {
    case 'session.started':
    case 'session.updated': return { kind: 'ready' }
    case 'session.closed': return { kind: 'closed' }
    case 'error': {
      const message = text(event.error?.message, 'error.message')
      const code = typeof event.error?.code === 'string' ? event.error.code : ''
      return { kind: 'error', text: `${code ? `${code}: ` : ''}${message}` }
    }
    case 'input_transcript.added':
    case 'output_transcript.added':
      return { kind: 'transcript', role: event.type === 'input_transcript.added' ? 'user' : 'assistant', text: text(event.item?.text, 'item.text'), done: false }
    case 'turn.done':
      if (event.turn?.role !== 'user' && event.turn?.role !== 'assistant') return { kind: 'other' }
      return { kind: 'transcript', role: event.turn.role, text: text(event.turn.transcript, 'turn.transcript'), done: true }
    case 'delegation.created': {
      const item = event.item
      if (item?.type !== 'delegation' || item?.target !== 'client') throw new Error('不支持的语音任务委派类型。')
      if (!Array.isArray(item.content)) throw new Error('语音任务缺少内容。')
      const content = item.content.map((part: { type: string; text: unknown }) => {
        if (part.type !== 'input_text') throw new Error('不支持的语音任务内容类型。')
        return text(part.text, 'content.text')
      }).join('')
      if (!content.trim()) throw new Error('语音任务内容为空。')
      return { kind: 'delegation', id: text(item.id, 'item.id'), text: content }
    }
    default: return { kind: 'other' }
  }
}

// Codex V3 context appends are limited to 500 UTF-8 bytes, not 500 characters.
export function voiceContextChunks(value: string): string[] {
  const encoder = new TextEncoder()
  const result: string[] = []
  let chunk = '', bytes = 0
  for (const char of value) {
    const size = encoder.encode(char).length
    if (bytes + size > 500) { result.push(chunk); chunk = ''; bytes = 0 }
    chunk += char; bytes += size
  }
  if (chunk) result.push(chunk)
  return result
}

export function delegationResult(id: string, value: string) {
  return voiceContextChunks(value).map(chunk => ({
    type: 'delegation.context.append', delegation_item_id: id, channel: 'speakable',
    content: [{ type: 'input_text', text: chunk }],
  }))
}
