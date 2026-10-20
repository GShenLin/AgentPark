import type { UserInteractionField, UserInteractionRequest } from './apiTypes'
import type { UploadedFileItem } from './uploadApi'

export type InteractionDraft = {
  values: Record<string, unknown>
  selectedFiles: Record<string, File[]>
  uploaded: Record<string, UploadedFileItem[]>
}

const drafts = new Map<string, InteractionDraft>()
function key(scope: string, id: string) { return `agentpark:interaction:${scope}:${id}` }

export function getInteractionDraft(request: UserInteractionRequest, scope: string, storage: Storage): InteractionDraft {
  const id = key(scope, request.id)
  const existing = drafts.get(id)
  if (existing) return existing
  const values: Record<string, unknown> = {}
  for (const field of request.schema.fields) {
    if (field.type === 'file') continue
    values[field.id] = field.default ?? (field.type === 'checkbox' ? false : field.type === 'multiselect' ? [] : '')
  }
  const saved = storage.getItem(id)
  const draft: InteractionDraft = { values, selectedFiles: {}, uploaded: {} }
  if (saved) {
    const parsed: unknown = JSON.parse(saved)
    if (!parsed || typeof parsed !== 'object' || !('values' in parsed) || !('uploaded' in parsed)
      || !parsed.values || typeof parsed.values !== 'object' || Array.isArray(parsed.values)
      || !parsed.uploaded || typeof parsed.uploaded !== 'object' || Array.isArray(parsed.uploaded)) {
      throw new Error('交互草稿格式无效，请清除该请求的草稿后重试。')
    }
    Object.assign(draft.values, parsed.values)
    Object.assign(draft.uploaded, parsed.uploaded)
    const valueIds = new Set(request.schema.fields.filter(field => field.type !== 'file').map(field => field.id))
    const fileIds = new Set(request.schema.fields.filter(field => field.type === 'file').map(field => field.id))
    if (Object.keys(draft.values).some(id => !valueIds.has(id)) || Object.keys(draft.uploaded).some(id => !fileIds.has(id))
      || Object.values(draft.uploaded).some(items => !Array.isArray(items) || items.some(item =>
        !item || typeof item.name !== 'string' || typeof item.path !== 'string'))) {
      throw new Error('交互草稿与当前表单不匹配。')
    }
  }
  drafts.set(id, draft)
  return draft
}

export function saveInteractionDraft(id: string, scope: string, draft: InteractionDraft, storage: Storage) {
  storage.setItem(key(scope, id), JSON.stringify({ values: draft.values, uploaded: draft.uploaded }))
}

export function clearInteractionDraft(id: string, scope: string, storage: Storage) {
  drafts.delete(key(scope, id))
  storage.removeItem(key(scope, id))
}

export function validateInteractionField(field: UserInteractionField, value: unknown): string {
  if (field.type === 'file') {
    if (!Array.isArray(value) || (field.required && !value.length)) return '请选择文件'
    if (!field.multiple && value.length > 1) return '只能选择一个文件'
  } else if (field.type === 'checkbox') {
    if (typeof value !== 'boolean' || (field.required && !value)) return '请勾选确认'
  } else if (field.type === 'multiselect') {
    if (!Array.isArray(value) || (field.required && !value.length)) return '请至少选择一项'
  } else if (typeof value !== 'string' || (field.required && !value.trim())) {
    return field.type === 'select' ? '请选择一项' : '请填写此项'
  }
  if (field.type === 'select' || field.type === 'multiselect') {
    const choices = field.type === 'multiselect' ? value as unknown[] : value ? [value] : []
    const allowed = new Set(field.options?.filter(option => !option.disabled).map(option => option.value))
    if (choices.some(choice => typeof choice !== 'string' || !allowed.has(choice)) || new Set(choices).size !== choices.length) return '包含无效或重复选项'
  }
  return ''
}

export function validateInteractionDraft(fields: UserInteractionField[], draft: InteractionDraft): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const field of fields) {
    const value = field.type === 'file'
      ? [...(draft.uploaded[field.id] || []), ...(draft.selectedFiles[field.id] || [])]
      : draft.values[field.id]
    const error = validateInteractionField(field, value)
    if (error) errors[field.id] = error
  }
  return errors
}
