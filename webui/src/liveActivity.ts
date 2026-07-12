function parseObject(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  if (typeof value !== 'string' || !value.trim()) return null
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null
  } catch {
    return null
  }
}

function findStringField(value: unknown, keys: string[], depth = 0): string {
  if (depth > 4 || value == null) return ''
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findStringField(item, keys, depth + 1)
      if (found) return found
    }
    return ''
  }
  if (typeof value !== 'object') return ''
  const item = value as Record<string, unknown>
  for (const key of keys) {
    const raw = item[key]
    if (typeof raw === 'string' && raw.trim()) return raw.trim()
    if (typeof raw === 'number' || typeof raw === 'boolean') return String(raw)
  }
  for (const raw of Object.values(item)) {
    const found = findStringField(raw, keys, depth + 1)
    if (found) return found
  }
  return ''
}

export function formatLiveActivity(eventType: string, eventData: Record<string, unknown> | null): string {
  const safeEventType = String(eventType || '').trim()
  if (safeEventType === 'server_tool_activity') return ''
  if (safeEventType !== 'runtime_notice' || !eventData) return ''
  const stage = String(eventData.stage || '').trim()
  if (stage !== 'openai_chat_native_web_search') return ''

  const payload = parseObject(eventData.message)
  if (!payload || String(payload.event || '') !== 'native_web_search') return 'Web search activity'
  const preview = parseObject(payload.preview)
  const query = findStringField(preview, ['query', 'keyword', 'keywords', 'search_query'])
  const status = findStringField(preview, ['status', 'state'])
  const suffix = status ? ` (${status})` : ''
  return query ? `Web search: ${query}${suffix}` : `Web search activity${suffix}`
}
