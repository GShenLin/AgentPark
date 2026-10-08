import type { MessageEnvelope } from '../api'
import { messageParts } from './memoryFeedTools'
import { voiceRecordData, voiceRecordText } from '../voice/voiceRecord'

export function extractMemoryMessageText(message: MessageEnvelope): string {
  return messageParts(message)
    .map((part) => {
      const voice = voiceRecordData(part)
      if (voice) return voiceRecordText(voice)
      return String((part as any)?.type || '') === 'text' ? String((part as any)?.text || '') : ''
    })
    .filter((text) => text.trim().length > 0)
    .join('\n\n')
}
