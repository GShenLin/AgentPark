import type { MemoryHistoryMode, MessageEnvelope } from './api'

function messageRole(message: MessageEnvelope) {
  return String(message?.role || '').trim().toLowerCase()
}

function messageId(message: MessageEnvelope) {
  return String(message?.id || '').trim()
}

export function resolveTurnDeletionHistoryMode(
  messages: MessageEnvelope[],
  deletedUserMessageId: string,
  historyComplete: boolean,
): MemoryHistoryMode {
  const targetId = String(deletedUserMessageId || '').trim()
  const latestUserMessage = [...messages]
    .reverse()
    .find((message) => ['user', 'human'].includes(messageRole(message)))

  if (!latestUserMessage || messageId(latestUserMessage) === targetId) {
    return 'latest_turn'
  }
  return historyComplete ? 'all' : 'latest_turn'
}
