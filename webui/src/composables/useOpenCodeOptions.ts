import { onScopeDispose, reactive, watch } from 'vue'
import { getOpenCodeOptions, type OpenCodeField, type NativeOption } from '../harnessApi'

export type OpenCodeCatalog = {
  loading: boolean
  error: string
  options: Record<OpenCodeField, NativeOption[]>
}

export function useOpenCodeOptions(props: { typeId: string; fields: Record<string, unknown> }) {
  const catalog = reactive<OpenCodeCatalog>({ loading: false, error: '',
    options: { native_model: [], native_agent: [], native_effort: [] } })
  let requestId = 0
  const isNativeField = (key: string): key is OpenCodeField => props.typeId === 'opencode_node'
    && ['native_model', 'native_agent', 'native_effort'].includes(key)

  async function refresh() {
    const current = ++requestId
    if (props.typeId !== 'opencode_node') return
    catalog.loading = true
    catalog.error = ''
    try {
      const result = await getOpenCodeOptions(String(props.fields.native_model ?? ''),
        String(props.fields.native_agent ?? ''), String(props.fields.working_path ?? ''))
      if (current !== requestId) return
      catalog.options = { native_model: result.native_model, native_agent: result.native_agent,
        native_effort: [{ value: '', label: '模型默认' }, ...result.native_effort] }
      catalog.error = result.selection_error
    } catch (cause) {
      if (current !== requestId) return
      catalog.options = { native_model: [], native_agent: [], native_effort: [] }
      catalog.error = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (current === requestId) catalog.loading = false
    }
  }
  watch(() => JSON.stringify([props.typeId, props.fields.native_model, props.fields.native_agent, props.fields.working_path]),
    (_, __, cleanup) => {
      ++requestId
      catalog.options = { native_model: [], native_agent: [], native_effort: [] }
      catalog.loading = props.typeId === 'opencode_node'
      if (!catalog.loading) return
      const timer = setTimeout(refresh, 150)
      cleanup(() => clearTimeout(timer))
    }, { immediate: true })
  onScopeDispose(() => { ++requestId })
  return { catalog, refresh, isNativeField }
}
