import { ref, watch, type Ref } from 'vue'
import { getNodeTemplate } from '../api'

type NodeFields = Record<string, any>
type NodeSchema = Record<string, any>

export function useProviderDrivenTemplateSchema(options: {
  typeId: Ref<string>
  fields: Ref<NodeFields>
  schema: Ref<NodeSchema>
  onError: (error: unknown) => void
}) {
  const loading = ref(false)
  let requestId = 0
  let loadedContextKey = ''

  function contextKey() {
    return [
      String(options.typeId.value || '').trim(),
      String(options.fields.value.provider_id || '').trim(),
    ].join('|')
  }

  watch(
    contextKey,
    async (key) => {
      const [typeId = '', providerId = ''] = key.split('|')
      requestId += 1
      const currentRequest = requestId
      if (!['agent_node', 'codex_node'].includes(typeId) || !providerId) {
        loadedContextKey = ''
        loading.value = false
        return
      }
      if (key === loadedContextKey) return
      loading.value = true
      try {
        const template = await getNodeTemplate(typeId, { providerId })
        if (currentRequest !== requestId) return
        options.schema.value = (template.schema || {}) as NodeSchema
        options.fields.value = {
          ...(template.fields || {}),
          ...options.fields.value,
        }
        loadedContextKey = key
      } catch (error) {
        if (currentRequest === requestId) options.onError(error)
      } finally {
        if (currentRequest === requestId) loading.value = false
      }
    },
  )

  return { loading }
}
