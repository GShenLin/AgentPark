type SchemaRecord = Record<string, any>

const capabilityFieldKeys = new Set(['plugins', 'tools', 'mcp_servers', 'skills'])

export function withPersistedCapabilityState(rawSchema: SchemaRecord, cfg: Record<string, unknown> | null): SchemaRecord {
  if (!rawSchema || typeof rawSchema !== 'object' || Array.isArray(rawSchema)) return {}
  const next: SchemaRecord = {}
  for (const [key, field] of Object.entries(rawSchema)) {
    if (!capabilityFieldKeys.has(key) || !field || typeof field !== 'object' || Array.isArray(field)) {
      next[key] = field
      continue
    }
    const selected = persistedStringSet(cfg?.[key])
    const seen = new Set<string>()
    const rawOptions = Array.isArray((field as SchemaRecord).options) ? (field as SchemaRecord).options : []
    const options = rawOptions.map((option: unknown) => {
      if (!option || typeof option !== 'object' || Array.isArray(option)) return option
      const value = String((option as Record<string, unknown>).value || '').trim()
      if (value) seen.add(value)
      const enabled = value ? selected.has(value) : false
      return {
        ...(option as Record<string, unknown>),
        enabled,
        status: enabled ? 'selected' : String((option as Record<string, unknown>).status || 'available'),
      }
    })
    for (const value of selected) {
      if (seen.has(value)) continue
      options.push({
        value,
        label: value,
        enabled: true,
        status: 'unavailable',
        diagnostics: [`selected ${capabilityKindLabel(key)} is not available: ${value}`],
        effective: 'next_agent_run',
      })
    }
    next[key] = {
      ...(field as Record<string, unknown>),
      options,
    }
  }
  return next
}

function persistedStringSet(value: unknown) {
  const result = new Set<string>()
  if (!Array.isArray(value)) return result
  for (const item of value) {
    const text = String(item || '').trim()
    if (text) result.add(text)
  }
  return result
}

function capabilityKindLabel(fieldKey: string) {
  if (fieldKey === 'mcp_servers') return 'mcp'
  if (fieldKey.endsWith('s')) return fieldKey.slice(0, -1)
  return fieldKey
}
