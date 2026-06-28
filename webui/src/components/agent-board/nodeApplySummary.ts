import type { NodeConfigChangeResponse } from '../../api'

export function formatNodeConfigChangeSummary(result: NodeConfigChangeResponse | void): string {
  if (!result) return 'Applied.'
  const changedFields = Array.isArray(result.changed_fields) ? result.changed_fields.map((item) => String(item)).filter(Boolean) : []
  const changedText = changedFields.length ? summarizeFields(changedFields) : 'No config fields changed'
  const effective = formatEffective(result.effective)
  const warnings = Array.isArray(result.warnings) ? result.warnings.map((item) => String(item || '').trim()).filter(Boolean) : []
  const warningText = warnings.length ? ` ${warnings.slice(0, 2).join(' ')}` : ''
  return `${changedText}. Effective: ${effective}.${warningText}`
}

export function normalizeApplyError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error || 'Apply failed')
  const trimmed = message.trim()
  const withoutHttpPrefix = trimmed.replace(/^HTTP\s+\d+:\s*/i, '').trim()
  return withoutHttpPrefix || trimmed || 'Apply failed'
}

function summarizeFields(fields: string[]) {
  const visible = fields.slice(0, 4)
  const suffix = fields.length > visible.length ? `, +${fields.length - visible.length} more` : ''
  return `${fields.length} field${fields.length === 1 ? '' : 's'} changed: ${visible.join(', ')}${suffix}`
}

function formatEffective(value: unknown) {
  const text = String(value || '').trim()
  if (text === 'next_agent_run') return 'next agent run'
  return text.replace(/_/g, ' ') || 'immediate'
}
