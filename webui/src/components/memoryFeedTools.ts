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

export type FeedProgressGroupEntry = Omit<FeedToolGroupEntry, 'type'> & {
  type: 'progress_group'
}

export type FeedTurnEntry = {
  type: 'turn'
  key: string
  userMessage: MessageEnvelope
  progressMessages: MessageEnvelope[]
  finalResponse: MessageEnvelope | null
  finalMessages: MessageEnvelope[]
  startIndex: number
}

export type TurnLazySection = 'progress' | 'metadata'

export type FeedEntry = FeedMessageEntry | FeedToolGroupEntry
export type MemoryTurnFeedEntry = FeedMessageEntry | FeedTurnEntry

export type MemoryMessageDisplayPart =
  | { kind: 'part'; key: string; part: unknown }
  | { kind: 'associated_metadata'; key: string; parts: unknown[]; createdAt: string }

export function normalizeMemoryRole(role: string) {
  const value = String(role || '').trim().toLowerCase()
  if (!value) return 'other'
  if (value.includes('user') || value.includes('human')) return 'user'
  if (value.includes('assistant_progress')) return 'progress'
  if (value.includes('assistant') || value.includes('agent')) return 'assistant'
  if (value.includes('system')) return 'system'
  if (value.includes('commentary') || value.includes('reasoning')) return 'commentary'
  if (value.includes('metadata')) return 'metadata'
  if (value.includes('tool')) return 'tool'
  const safe = value.replace(/[^a-z0-9_-]/g, '')
  return safe || 'other'
}

export function memoryRoleLabel(roleKey: string, rawRole: string) {
  if (roleKey === 'user') return 'User'
  if (roleKey === 'assistant') return 'Assistant'
  if (roleKey === 'progress') return 'Progress'
  if (roleKey === 'system') return 'System'
  if (roleKey === 'commentary') return 'Commentary'
  if (roleKey === 'metadata') return 'Metadata'
  if (roleKey === 'tool') return 'Tool'
  const text = String(rawRole || '').trim()
  return text || 'Other'
}

export function feedRoleClass(role: string) {
  const key = normalizeMemoryRole(role)
  if (key === 'user' || key === 'assistant' || key === 'progress' || key === 'system' || key === 'commentary' || key === 'metadata' || key === 'tool') return key
  return 'other'
}

export function messageKey(message: MessageEnvelope, index: number) {
  return String((message as any)?.id || `${index}-${String((message as any)?.created_at || '')}`)
}

function stableMessageKey(message: MessageEnvelope, index: number) {
  return String((message as any)?.id || (message as any)?.created_at || index)
}

export function isToolMessage(message: MessageEnvelope) {
  return feedRoleClass(String((message as any)?.role || '')) === 'tool'
}

export function messageParts(message: MessageEnvelope) {
  return Array.isArray((message as any)?.parts) ? ((message as any).parts as unknown[]) : []
}

export function responseMetadataPartData(part: unknown) {
  return (part as any)?.data as Record<string, unknown> | undefined
}

export function isResponseMetadataPart(part: unknown) {
  if (!part || typeof part !== 'object' || String((part as any).type || '') !== 'structured') return false
  const data = responseMetadataPartData(part)
  return !!(data && typeof data === 'object' && (
    data.response_metadata
    || data.provider_requests
    || Array.isArray(data.server_tool_calls)
    || Array.isArray(data.citations)
  ))
}

export function isAssociatedMetadataPart(part: unknown) {
  return isResponseMetadataPart(part)
    && String(responseMetadataPartData(part)?.display_placement || '') === 'associated'
}

export function memoryMessageDisplayParts(message: MessageEnvelope, groupAssociatedMetadata = true): MemoryMessageDisplayPart[] {
  const parts = messageParts(message)
  if (!groupAssociatedMetadata) {
    return parts.map((part, index) => ({ kind: 'part', key: `part-${index}`, part }))
  }

  const associatedParts = parts.filter(isAssociatedMetadataPart)
  if (associatedParts.length === 0) {
    return parts.map((part, index) => ({ kind: 'part', key: `part-${index}`, part }))
  }

  const createdTimes = associatedParts
    .map((part) => String(responseMetadataPartData(part)?.display_created_at || '').trim())
    .filter((value, index, values) => !!value && values.indexOf(value) === index)
  const createdAt = createdTimes.length > 1
    ? `${createdTimes[0]} - ${createdTimes[createdTimes.length - 1]}`
    : (createdTimes[0] || '')
  const firstAssociatedIndex = parts.findIndex(isAssociatedMetadataPart)

  return parts.flatMap((part, index): MemoryMessageDisplayPart[] => {
    if (!isAssociatedMetadataPart(part)) {
      return [{ kind: 'part', key: `part-${index}`, part }]
    }
    if (index !== firstAssociatedIndex) return []
    return [{
      kind: 'associated_metadata',
      key: `associated-metadata-${index}`,
      parts: associatedParts,
      createdAt,
    }]
  })
}

export function toolParts(message: MessageEnvelope) {
  return messageParts(message).filter((part) => String((part as any)?.type || '') === 'tool_call') as Record<string, unknown>[]
}

export function toolGroupParts(entry: FeedToolGroupEntry | FeedProgressGroupEntry) {
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

export function toolGroupLabel(entry: FeedToolGroupEntry | FeedProgressGroupEntry) {
  const count = toolGroupParts(entry).length || entry.messages.length
  return count === 1 ? '1 tool call' : `${count} tool calls`
}

export function lastToolPart(entry: FeedToolGroupEntry | FeedProgressGroupEntry) {
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

export function lastToolInstruction(entry: FeedToolGroupEntry | FeedProgressGroupEntry) {
  const last = lastToolPart(entry)
  return last ? toolInstruction(last) : ''
}

export function toolGroupTime(entry: FeedToolGroupEntry | FeedProgressGroupEntry) {
  const first = String((entry.messages[0] as any)?.created_at || '')
  const last = String((entry.messages[entry.messages.length - 1] as any)?.created_at || '')
  if (!first || first === last) return first
  return `${first} - ${last}`
}

function messageResponseMetadataData(message: MessageEnvelope) {
  for (const part of messageParts(message)) {
    if (String((part as any)?.type || '') !== 'structured') continue
    const data = (part as any)?.data
    if (data && typeof data === 'object' && String(data.kind || '') === 'response_metadata') return data as Record<string, any>
  }
  return null
}

function messageToolCallIds(message: MessageEnvelope) {
  return toolParts(message)
    .map((part) => String((part as any)?.call_id || '').trim())
    .filter(Boolean)
}

function associateMetadataSidecars(messages: MessageEnvelope[]) {
  const output = messages.map((message) => ({
    ...(message as any),
    parts: [...messageParts(message)],
  })) as MessageEnvelope[]
  const messageTargets = new Map<string, number>()
  const toolTargets = new Map<string, number[]>()

  output.forEach((message, index) => {
    const messageId = String((message as any)?.id || '').trim()
    if (messageId) messageTargets.set(messageId, index)
    for (const callId of messageToolCallIds(message)) {
      toolTargets.set(callId, [...(toolTargets.get(callId) || []), index])
    }
  })

  const hidden = new Set<number>()
  output.forEach((message, sidecarIndex) => {
    if (normalizeMemoryRole(String((message as any)?.role || '')) !== 'metadata') return
    const data = messageResponseMetadataData(message)
    const target = data?.target
    if (!target || typeof target !== 'object') return

    let targetIndex: number | undefined
    if (String(target.type || '') === 'message') {
      targetIndex = messageTargets.get(String(target.message_id || '').trim())
    } else if (String(target.type || '') === 'tool_calls' && Array.isArray(target.call_ids)) {
      for (const callId of target.call_ids) {
        const candidates = toolTargets.get(String(callId || '').trim()) || []
        targetIndex = candidates.find((candidate) => candidate > sidecarIndex) ?? candidates[0]
        if (targetIndex !== undefined) break
      }
    }
    if (targetIndex === undefined || targetIndex === sidecarIndex) return

    const targetMessage = output[targetIndex] as any
    const sidecarParts = messageParts(message).map((part) => ({
      ...(part as any),
      data: (part as any)?.data && typeof (part as any).data === 'object'
        ? {
            ...(part as any).data,
            display_placement: 'associated',
            display_created_at: String((message as any)?.created_at || ''),
          }
        : (part as any)?.data,
    }))
    targetMessage.parts = [...messageParts(targetMessage), ...sidecarParts]
    targetMessage.__associatedMetadataMessages = [
      ...(Array.isArray(targetMessage.__associatedMetadataMessages) ? targetMessage.__associatedMetadataMessages : []),
      message,
    ]
    hidden.add(sidecarIndex)
  })

  return output.filter((_message, index) => !hidden.has(index))
}

export function associatedMessages(message: MessageEnvelope) {
  const values = (message as any)?.__associatedMetadataMessages
  return Array.isArray(values) ? values as MessageEnvelope[] : []
}

export function prepareMemoryMessages(messages: MessageEnvelope[]) {
  return associateMetadataSidecars(messages)
}

export function useMemoryFeedEntries(messages: Ref<MessageEnvelope[]>) {
  return computed<FeedEntry[]>(() => {
    const entries: FeedEntry[] = []
    let toolRun: { messages: MessageEnvelope[]; startIndex: number } | null = null

    function flushToolRun() {
      if (!toolRun) return
      if (toolRun.messages.length === 1) {
        const message = toolRun.messages[0]
        if (message) {
          entries.push({ type: 'message', key: messageKey(message, toolRun.startIndex), message, index: toolRun.startIndex })
        }
      } else {
        const first = toolRun.messages[0]
        if (first) {
          entries.push({
            type: 'tool_group',
            key: `tool-group-${toolRun.startIndex}-${messageKey(first, toolRun.startIndex)}`,
            messages: [...toolRun.messages],
            startIndex: toolRun.startIndex,
          })
        }
      }
      toolRun = null
    }

    prepareMemoryMessages(messages.value).forEach((message, index) => {
      if (isToolMessage(message)) {
        if (!toolRun) toolRun = { messages: [], startIndex: index }
        toolRun.messages.push(message)
        return
      }
      flushToolRun()
      entries.push({ type: 'message', key: messageKey(message, index), message, index })
    })
    flushToolRun()
    return entries
  })
}

export function useMemoryTurnEntries(messages: Ref<MessageEnvelope[]>) {
  return computed<MemoryTurnFeedEntry[]>(() => {
    const entries: MemoryTurnFeedEntry[] = []

    function pushMessage(message: MessageEnvelope, index: number) {
      entries.push({
        type: 'message',
        key: messageKey(message, index),
        message,
        index,
      })
    }

    const source = associateMetadataSidecars(messages.value)
    let index = 0

    // Records written before the first user message are not part of a user turn.
    while (index < source.length && normalizeMemoryRole(String((source[index] as any)?.role || '')) !== 'user') {
      const message = source[index]
      if (message) pushMessage(message, index)
      index += 1
    }

    while (index < source.length) {
      const userMessage = source[index]
      if (!userMessage) break

      const bodyStart = index + 1
      let bodyEnd = bodyStart
      while (bodyEnd < source.length && normalizeMemoryRole(String((source[bodyEnd] as any)?.role || '')) !== 'user') {
        bodyEnd += 1
      }

      let finalResponseIndex = -1
      for (let candidate = bodyEnd - 1; candidate >= bodyStart; candidate -= 1) {
        const role = normalizeMemoryRole(String((source[candidate] as any)?.role || ''))
        if (role === 'assistant' || role === 'system') {
          finalResponseIndex = candidate
          break
        }
      }

      const progressMessages: MessageEnvelope[] = []
      const finalMessages: MessageEnvelope[] = []
      for (let bodyIndex = bodyStart; bodyIndex < bodyEnd; bodyIndex += 1) {
        if (bodyIndex === finalResponseIndex) continue
        const message = source[bodyIndex]
        if (!message) continue
        if (finalResponseIndex >= 0 && bodyIndex > finalResponseIndex) {
          finalMessages.push(message)
        } else {
          progressMessages.push(message)
        }
      }
      entries.push({
        type: 'turn',
        key: `turn-${stableMessageKey(userMessage, index)}`,
        userMessage,
        progressMessages,
        finalResponse: finalResponseIndex >= 0 ? (source[finalResponseIndex] || null) : null,
        finalMessages,
        startIndex: index,
      })
      index = bodyEnd
    }

    return entries
  })
}
