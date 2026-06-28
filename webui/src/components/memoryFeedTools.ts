import { computed, type Ref } from 'vue'
import type { MessageEnvelope } from '../api'

export type FeedMessageEntry = {
  type: 'message'
  key: string
  message: MessageEnvelope
  index: number
}

export type FeedToolGroupEntry = {
  type: 'tool_group'
  key: string
  messages: MessageEnvelope[]
  startIndex: number
}

export type FeedEntry = FeedMessageEntry | FeedToolGroupEntry

export function normalizeMemoryRole(role: string) {
  const value = String(role || '').trim().toLowerCase()
  if (!value) return 'other'
  if (value.includes('user') || value.includes('human')) return 'user'
  if (value.includes('assistant') || value.includes('agent')) return 'assistant'
  if (value.includes('system')) return 'system'
  if (value.includes('commentary') || value.includes('reasoning')) return 'commentary'
  if (value.includes('tool')) return 'tool'
  const safe = value.replace(/[^a-z0-9_-]/g, '')
  return safe || 'other'
}

export function memoryRoleLabel(roleKey: string, rawRole: string) {
  if (roleKey === 'user') return 'User'
  if (roleKey === 'assistant') return 'Assistant'
  if (roleKey === 'system') return 'System'
  if (roleKey === 'commentary') return 'Commentary'
  if (roleKey === 'tool') return 'Tool'
  const text = String(rawRole || '').trim()
  return text || 'Other'
}

export function feedRoleClass(role: string) {
  const key = normalizeMemoryRole(role)
  if (key === 'user' || key === 'assistant' || key === 'system' || key === 'commentary' || key === 'tool') return key
  return 'other'
}

export function messageKey(message: MessageEnvelope, index: number) {
  return String((message as any)?.id || `${index}-${String((message as any)?.created_at || '')}`)
}

export function isToolMessage(message: MessageEnvelope) {
  return feedRoleClass(String((message as any)?.role || '')) === 'tool'
}

export function messageParts(message: MessageEnvelope) {
  return Array.isArray((message as any)?.parts) ? ((message as any).parts as unknown[]) : []
}

export function toolParts(message: MessageEnvelope) {
  return messageParts(message).filter((part) => String((part as any)?.type || '') === 'tool_call') as Record<string, unknown>[]
}

export function toolGroupParts(entry: FeedToolGroupEntry) {
  return entry.messages.flatMap((message) => toolParts(message))
}

export function toolStatus(part: Record<string, unknown>) {
  return String(part.status || 'completed').trim() || 'completed'
}

export function toolName(part: Record<string, unknown>) {
  return String(part.name || 'tool').trim() || 'tool'
}

export function toolDuration(part: Record<string, unknown>) {
  const duration = part.duration_ms
  return typeof duration === 'number' ? `${Math.max(0, Math.round(duration))}ms` : ''
}

export function toolGroupLabel(entry: FeedToolGroupEntry) {
  const count = toolGroupParts(entry).length || entry.messages.length
  return count === 1 ? '1 tool call' : `${count} tool calls`
}

export function lastToolPart(entry: FeedToolGroupEntry) {
  const parts = toolGroupParts(entry)
  return parts.length > 0 ? parts[parts.length - 1] : null
}

export function toolInstruction(part: Record<string, unknown>) {
  const args = part.args ?? part.arguments
  if (!args || typeof args !== 'object') return toolName(part)
  try {
    return `${toolName(part)}\n${JSON.stringify(args, null, 2)}`
  } catch {
    return `${toolName(part)}\n${String(args)}`
  }
}

export function lastToolInstruction(entry: FeedToolGroupEntry) {
  const last = lastToolPart(entry)
  return last ? toolInstruction(last) : ''
}

export function toolGroupTime(entry: FeedToolGroupEntry) {
  const first = String((entry.messages[0] as any)?.created_at || '')
  const last = String((entry.messages[entry.messages.length - 1] as any)?.created_at || '')
  if (!first || first === last) return first
  return `${first} - ${last}`
}

export function useMemoryFeedEntries(messages: Ref<MessageEnvelope[]>) {
  return computed<FeedEntry[]>(() => {
    const entries: FeedEntry[] = []
    let toolRun: { messages: MessageEnvelope[]; startIndex: number } | null = null

    function flushToolRun() {
      if (!toolRun) return
      if (toolRun.messages.length === 1) {
        const message = toolRun.messages[0]
        if (!message) {
          toolRun = null
          return
        }
        entries.push({
          type: 'message',
          key: messageKey(message, toolRun.startIndex),
          message,
          index: toolRun.startIndex,
        })
      } else {
        const first = toolRun.messages[0]
        if (!first) {
          toolRun = null
          return
        }
        entries.push({
          type: 'tool_group',
          key: `tool-group-${toolRun.startIndex}-${messageKey(first, toolRun.startIndex)}`,
          messages: [...toolRun.messages],
          startIndex: toolRun.startIndex,
        })
      }
      toolRun = null
    }

    messages.value.forEach((message, index) => {
      if (isToolMessage(message)) {
        if (!toolRun) {
          toolRun = { messages: [], startIndex: index }
        }
        toolRun.messages.push(message)
        return
      }
      flushToolRun()
      entries.push({
        type: 'message',
        key: messageKey(message, index),
        message,
        index,
      })
    })
    flushToolRun()

    return entries
  })
}
