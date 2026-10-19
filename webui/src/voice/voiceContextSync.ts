import { voiceRequest, type VoiceTarget } from '../voiceApi'
import type { RealtimeDialogue } from './RealtimeDialogue'
import { voiceDelay, voiceRetry } from './voiceRetry'

export type VoiceContextMessage = { id: string; role: 'user' | 'assistant'; parts: (
  { type: 'text'; text: string } | { type: 'resource'; resource: { uri: string; kind: string; name?: string; mime?: string } }
)[] }

function contextPage(value: unknown): { cursor: string; messages: VoiceContextMessage[] } {
  const page = value as { cursor?: unknown; messages?: unknown }
  if (!page || typeof page.cursor !== 'string' || !Array.isArray(page.messages)) throw new Error('聊天同步返回了无效的数据。')
  for (const message of page.messages) {
    if (!message || typeof message.id !== 'string' || !['user', 'assistant'].includes(message.role) || !Array.isArray(message.parts)) {
      throw new Error('聊天同步消息格式无效。')
    }
    for (const part of message.parts) {
      if (part?.type === 'text' && typeof part.text === 'string') continue
      if (part?.type === 'resource' && typeof part.resource?.uri === 'string' && typeof part.resource?.kind === 'string') continue
      throw new Error('聊天同步内容格式无效。')
    }
  }
  return page as { cursor: string; messages: VoiceContextMessage[] }
}

export async function syncVoiceContext(target: VoiceTarget, session: string, dialogue: RealtimeDialogue,
  signal: AbortSignal, status: (message: string) => void) {
  let cursor: string | undefined
  while (!signal.aborted) {
    const page = contextPage(await voiceRetry(() => voiceRequest(target,
      `/${encodeURIComponent(session)}/context${cursor === undefined ? '' : `?after=${encodeURIComponent(cursor)}`}`, { signal }), signal, status))
    for (const message of page.messages) await dialogue.contextMessage(message)
    // Move the cursor only after every message has been acknowledged by Realtime.
    cursor = page.cursor
    status('')
    await voiceDelay(signal, 1000)
  }
}
