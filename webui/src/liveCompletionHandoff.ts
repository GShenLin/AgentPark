import type { MessageEnvelope } from './api'

export const LIVE_STREAM_FINISHED_EVENT = 'node_message_done'
export const LIVE_OUTPUT_COMMITTED_EVENT = 'node_output'

export type LiveCompletionHandoff =
  | { status: 'empty'; text: ''; traceId: string }
  | { status: 'committed'; text: string; traceId: string }
  | { status: 'pending'; text: string; traceId: string }

const nonTerminalMemoryRoles = new Set(['user', 'human', 'assistant_progress', 'metadata', 'tool'])

export function isLiveCompletionEvent(eventType: string): boolean {
  return eventType === LIVE_STREAM_FINISHED_EVENT || eventType === LIVE_OUTPUT_COMMITTED_EVENT
}

function messageText(message: MessageEnvelope): string {
  const parts = Array.isArray(message?.parts) ? message.parts : []
  return parts
    .filter((part) => part && part.type === 'text')
    .map((part) => String((part as { text?: unknown }).text || ''))
    .join('\n')
    .trim()
}

function isTerminalMemoryMessage(message: MessageEnvelope): boolean {
  const role = String(message?.role || '').trim().toLowerCase()
  return !!role && !nonTerminalMemoryRoles.has(role)
}

export function resolveLiveCompletionHandoff(
  messages: MessageEnvelope[],
  text: string,
  traceId: string,
): LiveCompletionHandoff {
  const safeText = String(text || '').trim()
  const safeTraceId = String(traceId || '').trim()
  if (!safeText) return { status: 'empty', text: '', traceId: safeTraceId }

  const terminalMessages = messages.filter(isTerminalMemoryMessage)
  const committed = safeTraceId
    ? terminalMessages.some((message) => String(message?.trace_id || '').trim() === safeTraceId)
    : terminalMessages.some((message) => messageText(message) === safeText)

  return committed
    ? { status: 'committed', text: safeText, traceId: safeTraceId }
    : { status: 'pending', text: safeText, traceId: safeTraceId }
}
