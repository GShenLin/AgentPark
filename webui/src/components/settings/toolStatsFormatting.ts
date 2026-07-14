import type { ToolCallStatRecord } from '../../settingsApi'

export function callKey(call: ToolCallStatRecord) {
  return `${call.recorded_at}:${call.call_id}:${call.tool_name}`
}

export function shortText(value: string, fallback = '-') {
  const text = String(value || '').trim()
  return text || fallback
}

export function statusLabel(call: ToolCallStatRecord) {
  return call.success ? 'success' : shortText(call.status, 'failed')
}

export function formatStructuredValue(value: unknown, fallback = '-') {
  if (value === null || value === undefined || value === '') return fallback
  if (typeof value === 'string') {
    const text = value.trim()
    if (!text) return fallback
    try {
      return JSON.stringify(JSON.parse(text), null, 2)
    } catch {
      return text
    }
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function invocationLabel(call: ToolCallStatRecord) {
  return Object.prototype.hasOwnProperty.call(call.tool_call_arguments || {}, 'command')
    ? 'Exact command'
    : 'Invocation arguments'
}

export function invocationText(call: ToolCallStatRecord) {
  const args = call.tool_call_arguments
  if (args && Object.prototype.hasOwnProperty.call(args, 'command')) {
    return formatStructuredValue(args.command)
  }
  if (args) return formatStructuredValue(args)
  return formatStructuredValue(call.tool_call_arguments_json)
}

export function failureReason(call: ToolCallStatRecord) {
  if (call.success) return 'This call was recorded as successful.'
  const errorText = String(call.error || '').trim()
  if (errorText) return errorText
  const diagnostics = Array.isArray(call.diagnostics)
    ? call.diagnostics.map((item) => String(item || '').trim()).filter(Boolean)
    : []
  if (diagnostics.length) return diagnostics.join('\n')
  return `No explicit error message was recorded. Runtime status: ${shortText(call.status, 'failed')}. Inspect the complete result below.`
}
