export type NodeSchemaField = Record<string, any>
export type NodeSchema = Record<string, NodeSchemaField>

export type NodeSchemaOption = {
  value: string
  label: string
}

function normalizeSchemaField(field: unknown): NodeSchemaField {
  return field && typeof field === 'object' && !Array.isArray(field) ? (field as NodeSchemaField) : {}
}

export function getSchemaField(schema: NodeSchema | null | undefined, key: string): NodeSchemaField {
  return normalizeSchemaField(schema?.[key])
}

export function getSchemaFieldType(schema: NodeSchema | null | undefined, key: string): string {
  const type = getSchemaField(schema, key).type
  return String(type || 'text')
}

export function getSchemaFieldLabel(schema: NodeSchema | null | undefined, key: string): string {
  const label = getSchemaField(schema, key).label
  return String(label || key)
}

export function getSchemaFieldHint(schema: NodeSchema | null | undefined, key: string): string {
  const field = getSchemaField(schema, key)
  const hint = field.description ?? field.hint
  return String(hint || '').trim()
}

export function getSchemaFieldText(schema: NodeSchema | null | undefined, key: string, value: unknown): string {
  if (getSchemaFieldType(schema, key) === 'json' && value != null && typeof value === 'object') {
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return String(value)
    }
  }
  return String(value ?? '')
}

export function getSchemaInputType(schema: NodeSchema | null | undefined, key: string): string {
  return getSchemaFieldType(schema, key) === 'number' ? 'number' : 'text'
}

export function isSchemaBooleanValue(value: unknown): boolean {
  if (typeof value === 'boolean') return value
  const text = String(value ?? '').trim().toLowerCase()
  return ['true', '1', 'yes', 'on', 'enabled'].includes(text)
}

export function isSchemaSelectField(schema: NodeSchema | null | undefined, key: string): boolean {
  const field = getSchemaField(schema, key)
  if (String(field.type || '').trim().toLowerCase() === 'select') return true
  return Array.isArray(field.options) && field.options.length > 0
}

export function getSchemaFieldOptions(schema: NodeSchema | null | undefined, key: string): NodeSchemaOption[] {
  const field = getSchemaField(schema, key)
  const rawOptions = Array.isArray(field.options) ? field.options : []
  return rawOptions
    .map((option) => {
      if (option && typeof option === 'object' && !Array.isArray(option)) {
        const value = (option as Record<string, unknown>).value
        const label = (option as Record<string, unknown>).label
        return {
          value: String(value ?? ''),
          label: String(label ?? value ?? ''),
        }
      }
      return {
        value: String(option ?? ''),
        label: String(option ?? ''),
      }
    })
    .filter((option) => option.label !== '')
}

export function getSchemaInputAttrs(schema: NodeSchema | null | undefined, key: string): Record<string, string | number> {
  const field = getSchemaField(schema, key)
  const attrs: Record<string, string | number> = {}
  const placeholder = String(field.placeholder || '').trim()
  if (placeholder) attrs.placeholder = placeholder
  for (const attrKey of ['min', 'max', 'step'] as const) {
    const value = field[attrKey]
    if (typeof value === 'number' && Number.isFinite(value)) {
      attrs[attrKey] = value
    } else if (typeof value === 'string' && value.trim()) {
      attrs[attrKey] = value.trim()
    }
  }
  return attrs
}

function getSchemaValueType(schema: NodeSchema | null | undefined, key: string): string {
  const field = getSchemaField(schema, key)
  const explicit = String(field.value_type || field.valueType || '').trim().toLowerCase()
  if (explicit) return explicit
  const type = getSchemaFieldType(schema, key)
  if (type === 'number') return 'number'
  if (type === 'boolean') return 'boolean'
  return 'string'
}

export function normalizeSchemaFieldValue(schema: NodeSchema | null | undefined, key: string, value: unknown): any {
  const type = getSchemaFieldType(schema, key)
  if (type === 'json') {
    if (typeof value !== 'string') return value
    try {
      return JSON.parse(value)
    } catch {
      return value
    }
  }

  if (value == null) return value

  const valueType = getSchemaValueType(schema, key)
  if (valueType === 'number') {
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && value.trim() === '') return ''
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : value
  }

  if (valueType === 'boolean') {
    if (typeof value === 'boolean') return value
    if (typeof value === 'string' && value.trim() === '') return ''
    return String(value).toLowerCase() === 'true'
  }

  return value
}
