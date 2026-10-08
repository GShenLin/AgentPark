/** Shared by desktop, mobile, and creation forms; catalogs come from the backend. */
type Option = { id: string; label: string }
type Model = Option & { voices: Option[] }
type Catalog = { id: string; label: string; delegation: boolean; node_owned_dialogue: boolean; models: Model[] }
type Fields = Record<string, unknown>
type Schema = Record<string, any>

function catalogs(schema: Schema): Record<string, Catalog> {
  return schema.voice_provider_id?.catalogs || {}
}

export function voiceFieldOptions(schema: Schema, fields: Fields, key: string) {
  if (key !== 'voice_model' && key !== 'voice') return undefined
  if (!fields.voice_provider_id) return [{ value: String(fields[key] || ''), label: '请先选择语音 Provider' }]
  const catalog = catalogs(schema)[String(fields.voice_provider_id || '')]
  const model = catalog?.models.find(item => item.id === fields.voice_model)
  const values = (key === 'voice_model' ? catalog?.models : model?.voices) || []
  const options = values.map(item => ({ value: item.id, label: item.label }))
  const current = String(fields[key] || '')
  if (current && !values.some(item => item.id === current)) {
    options.unshift({ value: current, label: `${current}（当前配置不可用，请重新选择）` })
  } else if (!current) options.unshift({ value: '', label: '请选择' })
  return options
}

export function voiceFieldChanges(schema: Schema, fields: Fields, key: string, value: unknown): Fields {
  if (key === 'voice_provider_id') {
    const model = catalogs(schema)[String(value)]?.models[0]
    return { voice_provider_id: value, voice_model: model?.id || '', voice: model?.voices[0]?.id || '' }
  }
  if (key === 'voice_model') {
    const model = catalogs(schema)[String(fields.voice_provider_id)]?.models.find(item => item.id === value)
    return { voice_model: value, voice: model?.voices[0]?.id || '' }
  }
  return { [key]: value }
}

export function voiceProviderHint(schema: Schema, fields: Fields): string {
  const provider = catalogs(schema)[String(fields.voice_provider_id)]
  if (!provider) return ''
  return provider.delegation ? '自然语音交谈；需要执行任务时委派给原节点，沿用节点主模型、历史和工具。' : '此供应商暂不支持节点任务委派。'
}
