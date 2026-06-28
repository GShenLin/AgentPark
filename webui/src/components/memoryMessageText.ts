import type { MessageEnvelope } from '../api'
import { messageParts } from './memoryFeedTools'

export function extractMemoryMessageText(message: MessageEnvelope): string {
  return messageParts(message)
    .filter((part) => String((part as any)?.type || '') === 'text')
    .map((part) => String((part as any)?.text || ''))
    .filter((text) => text.trim().length > 0)
    .join('\n\n')
}
