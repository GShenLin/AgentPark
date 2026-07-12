import type { RuntimeEvent, RuntimeNoticeEvent, RuntimeToolCall, ServerToolActivityEvent, ToolRuntimeEvent } from '../../api'

export type ToolCallView = {
  id: string
  name: string
  status: string
  preview: string
  diagnostics: string[]
  argumentsPreview: string
  argumentsJson: string
  duration: string
  tone: 'running' | 'done' | 'attention'
}

function stringifyJson(value: unknown, pretty = false) {
  if (!value || typeof value !== 'object') return ''
  try {
    return JSON.stringify(value, null, pretty ? 2 : 0)
  } catch {
    return String(value)
  }
}

function compactArgumentsPreview(value: unknown) {
  const raw = stringifyJson(value, false)
  if (!raw) return ''
  return raw.length > 160 ? `${raw.slice(0, 157)}...` : raw
}

export function normalizeRuntimeEvent(value: unknown): RuntimeEvent | null {
  if (!value || typeof value !== 'object') return null
  const event = value as Record<string, unknown>
  const type = String(event.type || '').trim()
  if (type === 'runtime_notice') {
    const message = String(event.message || '').trim()
    if (!message) return null
    return {
      type,
      message,
      source: event.source != null ? String(event.source) : undefined,
      stage: event.stage != null ? String(event.stage) : undefined,
      name: event.name != null ? String(event.name) : undefined,
      call_id: event.call_id != null ? String(event.call_id) : null,
      provider: event.provider != null ? String(event.provider) : null,
    } satisfies RuntimeNoticeEvent
  }
  if (type === 'server_tool_activity') {
    const callId = String(event.call_id || '').trim()
    const toolType = String(event.tool_type || '').trim()
    if (!callId || !toolType) return null
    return {
      type,
      call_id: callId,
      tool_type: toolType,
      status: String(event.status || 'in_progress').trim() || 'in_progress',
      provider: event.provider != null ? String(event.provider) : null,
      action: event.action && typeof event.action === 'object' ? event.action as Record<string, unknown> : undefined,
      sources: Array.isArray(event.sources)
        ? event.sources.filter((item): item is { url: string; title?: string; type?: string } => !!item && typeof item === 'object' && typeof item.url === 'string')
        : undefined,
    } satisfies ServerToolActivityEvent
  }
  if (type !== 'tool_call_start' && type !== 'tool_call_end') return null
  return {
    type,
    name: event.name != null ? String(event.name) : undefined,
    call_id: event.call_id != null ? String(event.call_id) : null,
    provider: event.provider != null ? String(event.provider) : null,
    arguments: event.arguments && typeof event.arguments === 'object' ? (event.arguments as Record<string, unknown>) : undefined,
    status: event.status != null ? String(event.status) : undefined,
    duration_ms: typeof event.duration_ms === 'number' ? event.duration_ms : undefined,
    error: event.error != null ? String(event.error) : undefined,
    result_preview: event.result_preview != null ? String(event.result_preview) : undefined,
    result_chars: typeof event.result_chars === 'number' ? event.result_chars : undefined,
    result_preview_truncated:
      typeof event.result_preview_truncated === 'boolean' ? event.result_preview_truncated : undefined,
    diagnostics: Array.isArray(event.diagnostics) ? event.diagnostics.map((item) => String(item)) : undefined,
  }
}

export function normalizeRuntimeEvents(value: unknown): RuntimeEvent[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => normalizeRuntimeEvent(item))
    .filter((item): item is RuntimeEvent => !!item)
    .slice(-20)
}

export function normalizeToolRuntimeEvent(value: unknown): ToolRuntimeEvent | null {
  const event = normalizeRuntimeEvent(value)
  if (!event || event.type === 'runtime_notice' || event.type === 'server_tool_activity') return null
  return event
}

export function normalizeToolRuntimeEvents(value: unknown): ToolRuntimeEvent[] {
  return normalizeRuntimeEvents(value).filter((item): item is ToolRuntimeEvent => item.type === 'tool_call_start' || item.type === 'tool_call_end')
}

export function latestRuntimeNotice(events: RuntimeEvent[] | undefined | null): RuntimeNoticeEvent | null {
  if (!Array.isArray(events)) return null
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (event && event.type === 'runtime_notice') return event
  }
  return null
}

export function normalizeRuntimeToolCall(value: unknown): RuntimeToolCall | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Record<string, unknown>
  const callId = String(item.call_id || '').trim()
  if (!callId) return null
  const status = String(item.status || '').trim() || 'running'
  return {
    call_id: callId,
    name: item.name != null ? String(item.name) : undefined,
    provider: item.provider != null ? String(item.provider) : null,
    arguments: item.arguments && typeof item.arguments === 'object' ? (item.arguments as Record<string, unknown>) : null,
    status,
    duration_ms: typeof item.duration_ms === 'number' ? item.duration_ms : null,
    error: item.error != null ? String(item.error) : null,
    result_preview: item.result_preview != null ? String(item.result_preview) : null,
    result_chars: typeof item.result_chars === 'number' ? item.result_chars : null,
    result_preview_truncated:
      typeof item.result_preview_truncated === 'boolean' ? item.result_preview_truncated : null,
    diagnostics: Array.isArray(item.diagnostics) ? item.diagnostics.map((entry) => String(entry)) : null,
  }
}

export function normalizeRuntimeToolCalls(value: unknown): RuntimeToolCall[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => normalizeRuntimeToolCall(item))
    .filter((item): item is RuntimeToolCall => !!item)
    .slice(-20)
}

export function buildToolCallViewsFromCalls(calls: RuntimeToolCall[] | undefined | null): ToolCallView[] {
  return normalizeRuntimeToolCalls(calls).map((call) => {
    const status = String(call.status || 'running').trim() || 'running'
    const durationMs = typeof call.duration_ms === 'number' ? Math.max(0, Math.round(call.duration_ms)) : null
    const diagnostics = Array.isArray(call.diagnostics) ? call.diagnostics.map((item) => String(item)).filter(Boolean) : []
    const preview = formatResultPreview(call.error, call.result_preview, call.result_chars, call.result_preview_truncated)
    const argumentsPreview = compactArgumentsPreview(call.arguments)
    const argumentsJson = stringifyJson(call.arguments, true)
    return {
      id: call.call_id,
      name: String(call.name || 'tool').trim() || 'tool',
      status,
      preview,
      diagnostics,
      argumentsPreview,
      argumentsJson,
      duration: durationMs != null ? `${durationMs}ms` : '',
      tone: status === 'running' ? 'running' : status === 'completed' ? 'done' : 'attention',
    } satisfies ToolCallView
  })
}

export function buildRuntimeToolCallViews(
  calls: RuntimeToolCall[] | undefined | null,
  events: RuntimeEvent[] | ToolRuntimeEvent[] | undefined | null,
): ToolCallView[] {
  const callViews = buildToolCallViewsFromCalls(calls)
  return callViews.length ? callViews : buildToolCallViews(events)
}

export function buildToolCallViews(events: RuntimeEvent[] | ToolRuntimeEvent[] | undefined | null): ToolCallView[] {
  const normalized = normalizeToolRuntimeEvents(events)
  const order: string[] = []
  const calls = new Map<string, ToolRuntimeEvent[]>()

  normalized.forEach((event, index) => {
    const key = String(event.call_id || '').trim() || `${event.name || 'tool'}-${index}`
    if (!calls.has(key)) {
      calls.set(key, [])
      order.push(key)
    }
    calls.get(key)?.push(event)
  })

  return order
    .map((key) => {
      const items = calls.get(key) || []
      const start = items.find((item) => item.type === 'tool_call_start')
      const end = [...items].reverse().find((item) => item.type === 'tool_call_end')
      const latest = end || items[items.length - 1] || start
      if (!latest) return null
      const name = String(latest.name || start?.name || 'tool').trim() || 'tool'
      const status = String(end?.status || (latest.type === 'tool_call_start' ? 'running' : 'completed')).trim()
      const durationMs = typeof end?.duration_ms === 'number' ? Math.max(0, Math.round(end.duration_ms)) : null
      const preview = formatResultPreview(end?.error, end?.result_preview, end?.result_chars, end?.result_preview_truncated)
      const diagnostics = Array.isArray(end?.diagnostics) ? end.diagnostics.map((item) => String(item)).filter(Boolean) : []
      const argumentsSource = end?.arguments || start?.arguments || null
      const argumentsPreview = compactArgumentsPreview(argumentsSource)
      const argumentsJson = stringifyJson(argumentsSource, true)
      return {
        id: key,
        name,
        status,
        preview,
        diagnostics,
        argumentsPreview,
        argumentsJson,
        duration: durationMs != null ? `${durationMs}ms` : '',
        tone: latest.type === 'tool_call_start' && !end ? 'running' : status === 'completed' ? 'done' : 'attention',
      } satisfies ToolCallView
    })
    .filter((item): item is ToolCallView => !!item)
}

function formatResultPreview(
  error: unknown,
  resultPreview: unknown,
  resultChars: unknown,
  previewTruncated: unknown,
) {
  const errorText = String(error || '').trim()
  if (errorText) return errorText
  const preview = String(resultPreview || '').trim()
  const total = typeof resultChars === 'number' ? Math.max(0, Math.round(resultChars)) : null
  const truncated = previewTruncated === true
  if (!preview && total === 0) return '(empty result)'
  if (!truncated) return preview
  const suffix = total != null ? ` (${total} chars total)` : ''
  return preview ? `Result preview${suffix}: ${preview}` : `Result preview omitted${suffix}`
}
