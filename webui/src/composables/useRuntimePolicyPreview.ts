import { ref, type Ref } from 'vue'

import {
  previewAgentRuntimePolicy,
  type RuntimePolicyPreview,
} from '../api'
import { normalizeSchemaFieldValue } from './nodeSchemaFields'

type RuntimePolicyPreviewOptions = {
  fieldSchema: Ref<Record<string, any>>
  fields: Ref<Record<string, any>>
  onStart?: () => void
  onError: (error: unknown) => void
}

export function useRuntimePolicyPreview(options: RuntimePolicyPreviewOptions) {
  const preview = ref<RuntimePolicyPreview | null>(null)
  const resolving = ref(false)

  function clear() {
    preview.value = null
  }

  function normalizedDraft() {
    const value = normalizeSchemaFieldValue(
      options.fieldSchema.value,
      'runtime_policy',
      options.fields.value.runtime_policy,
    )
    if (typeof value === 'string' && value.trim()) {
      throw new Error('Runtime policy must be valid JSON.')
    }
    return value == null || value === '' ? null : value
  }

  async function resolve() {
    if (resolving.value) return
    resolving.value = true
    options.onStart?.()
    try {
      preview.value = await previewAgentRuntimePolicy(normalizedDraft())
    } catch (error) {
      clear()
      options.onError(error)
    } finally {
      resolving.value = false
    }
  }

  return {
    preview,
    resolving,
    clear,
    resolve,
  }
}
