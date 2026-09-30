import { computed, type Ref } from 'vue'
import type { ProviderInfo } from '../api'

type NodeFields = Record<string, any>

export const AGENT_SUPPORT_MODE_ORDER = ['chat', 'image_generation', 'video_generation', 'audio_generation', 'vision_understand'] as const

export const switchOptions = [
  { value: 'enabled', label: 'enabled' },
  { value: 'disabled', label: 'disabled' },
]

export const reasoningEffortOptions = [
  { value: 'none', label: 'None' },
  { value: 'minimal', label: 'minimal' },
  { value: 'low', label: 'low' },
  { value: 'medium', label: 'medium' },
  { value: 'high', label: 'high' },
  { value: 'xhigh', label: 'xhigh' },
  { value: 'max', label: 'max' },
]

export const CODEX_NODE_TYPE = 'codex_node'
export const CLAUDE_NODE_TYPE = 'claude_node'
export const HARNESS_NODE_TYPES = [CODEX_NODE_TYPE, CLAUDE_NODE_TYPE, 'openclaw_node', 'deepseek_harness_node', 'pi_node', 'hermes_agent_node', 'minimax_code_node']
export const AUDIO_GENERATION_MODE = 'audio_generation'

export function dedupeStrings(values: unknown[]): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const item of values) {
    const value = String(item ?? '').trim()
    if (!value) continue
    if (seen.has(value)) continue
    seen.add(value)
    result.push(value)
  }
  return result
}

export function normalizeMode(value: unknown) {
  return String(value ?? '').trim()
}

function normalizeModeList(values: unknown): string[] {
  if (!Array.isArray(values)) return []
  return dedupeStrings(values.map((item) => normalizeMode(item)))
}

export function normalizeSwitch(value: unknown, fallback: 'enabled' | 'disabled' = 'disabled'): 'enabled' | 'disabled' {
  const text = String(value ?? '').trim()
  if (text === 'enabled') return 'enabled'
  if (text === 'disabled') return 'disabled'
  return fallback
}

export type ReasoningEffort = 'none' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export function providerReasoningEffortOptions(
  provider: Pick<ProviderInfo, 'features'> | null | undefined,
) {
  const feature = provider?.features?.reasoning_effort
  const values = Array.isArray(feature?.values)
    ? dedupeStrings(feature.values.map((value) => String(value || '').trim()))
    : []
  if (!feature?.supported || values.length === 0) return reasoningEffortOptions
  const labels = new Map(reasoningEffortOptions.map((option) => [option.value, option.label]))
  return values.map((value) => ({
    value,
    label: labels.get(value) || value,
  }))
}

export function providerThinkingDefault(
  provider: Pick<ProviderInfo, 'features'> | null | undefined,
): 'enabled' | 'disabled' {
  return normalizeSwitch(provider?.features?.thinking?.default, 'disabled')
}

export function providerModes(provider: Pick<ProviderInfo, 'supportmode'>) {
  return normalizeModeList(provider?.supportmode)
}

export function providerModelIds(provider: Pick<ProviderInfo, 'model' | 'models'> | null | undefined): string[] {
  const values = Array.isArray(provider?.models)
    ? provider.models
    : provider?.model ? [provider.model] : []
  return dedupeStrings(values)
}

export function agentProviderModes(provider: Pick<ProviderInfo, 'supportmode' | 'type'>): string[] {
  const supported = new Set<string>(AGENT_SUPPORT_MODE_ORDER)
  return providerModes(provider).filter((mode) => supported.has(mode))
}

export function cliProviderModes(provider: Pick<ProviderInfo, 'supportmode'>): string[] {
  return providerModes(provider).filter((mode) => mode === 'chat')
}

export function resolveAgentProviderSchemaContext(
  providers: ProviderInfo[],
  fields: NodeFields | null | undefined,
) {
  const providerId = String(fields?.provider_id || '').trim()
  const provider = providers.find((item) => String(item.id || '').trim() === providerId)
  return { providerId: provider && agentProviderModes(provider).length ? providerId : '' }
}

export function normalizeToolSelection(value: unknown, allowedTools: string[]): string[] {
  if (!Array.isArray(value)) return []
  const allowed = new Set(allowedTools)
  const seen = new Set<string>()
  const result: string[] = []
  for (const item of value) {
    if (typeof item !== 'string') continue
    const text = item.trim()
    if (!text || !allowed.has(text) || seen.has(text)) continue
    seen.add(text)
    result.push(text)
  }
  return result
}

export function useAgentNodeCreateSchema(options: {
  selectedTypeId: Ref<string>
  selectedNodeFields: Ref<NodeFields>
  providers: Ref<ProviderInfo[]>
  availableTools: Ref<string[]>
}) {
  const { selectedTypeId, selectedNodeFields, providers, availableTools } = options
  let lastAgentProviderId = ''

  const createProviderOptions = computed(() => {
    const ids = providers.value
      .filter((provider) => (
        HARNESS_NODE_TYPES.includes(selectedTypeId.value)
            ? cliProviderModes(provider).length > 0
            : agentProviderModes(provider).length > 0
      ))
      .map((provider) => String(provider.id || '').trim())
      .filter(Boolean)
    return dedupeStrings(ids).sort((a, b) => a.localeCompare(b))
  })

  const toolOptions = computed(() => dedupeStrings(availableTools.value).sort((a, b) => a.localeCompare(b)))

  const createToolSelection = computed<string[]>({
    get() {
      return normalizeToolSelection(selectedNodeFields.value.tools, toolOptions.value)
    },
    set(value) {
      selectedNodeFields.value.tools = normalizeToolSelection(value, toolOptions.value)
    },
  })

  function isCreateProviderField(key: string) {
    if (key !== 'provider_id') return false
    return (
      selectedTypeId.value === 'agent_node' ||
      HARNESS_NODE_TYPES.includes(selectedTypeId.value)
    )
  }

  function isCreateToolsField(key: string) {
    return selectedTypeId.value === 'agent_node' && key === 'tools'
  }

  function isCreateWebSearchField(key: string) {
    return selectedTypeId.value === 'agent_node' && key === 'web_search'
  }

  function isCreateThinkingField(key: string) {
    return selectedTypeId.value === 'agent_node' && key === 'thinking'
  }

  function isCreateReasoningEffortField(key: string) {
    return selectedTypeId.value === 'agent_node' && key === 'reasoning_effort'
  }

  function ensureCreateAgentSelections() {
    if (
      selectedTypeId.value !== 'agent_node' &&
      !HARNESS_NODE_TYPES.includes(selectedTypeId.value)
    ) {
      lastAgentProviderId = ''
      return
    }

    let providerId = String(selectedNodeFields.value.provider_id || '').trim()
    if (createProviderOptions.value.length) {
      if (!createProviderOptions.value.includes(providerId)) {
        providerId = createProviderOptions.value[0] || ''
        selectedNodeFields.value.provider_id = providerId
      }
    } else {
      selectedNodeFields.value.provider_id = ''
      providerId = ''
    }

    if (HARNESS_NODE_TYPES.includes(selectedTypeId.value)) {
      const selectedProvider = providers.value.find(item => item.id === providerId)
      const modelIds = providerModelIds(selectedProvider)
      if (!modelIds.includes(String(selectedNodeFields.value.model || ''))) selectedNodeFields.value.model = modelIds[0] || ''
      if (['hermes_agent_node', 'openclaw_node', 'minimax_code_node'].includes(selectedTypeId.value)) {
        const feature = selectedProvider?.features?.reasoning_effort
        const efforts = feature?.supported ? feature.values || [] : []
        if (!efforts.includes(String(selectedNodeFields.value.reasoning_effort || ''))) {
          selectedNodeFields.value.reasoning_effort = efforts[0] || ''
        }
      }
    }
    if (selectedTypeId.value === 'agent_node') {
      const selectedProvider = providers.value.find((provider) => String(provider.id || '').trim() === providerId)
      const modelIds = providerModelIds(selectedProvider)
      const modelId = String(selectedNodeFields.value.model || '').trim()
      if (!modelIds.includes(modelId)) selectedNodeFields.value.model = modelIds[0] || ''
      selectedNodeFields.value.tools = normalizeToolSelection(selectedNodeFields.value.tools, toolOptions.value)
      selectedNodeFields.value.web_search = normalizeSwitch(selectedNodeFields.value.web_search, 'disabled')
      const thinkingDefault = providerThinkingDefault(selectedProvider)
      selectedNodeFields.value.thinking = providerId !== lastAgentProviderId
        ? thinkingDefault
        : normalizeSwitch(selectedNodeFields.value.thinking, thinkingDefault)
      lastAgentProviderId = providerId
      if (selectedNodeFields.value.reasoning_effort == null) {
        selectedNodeFields.value.reasoning_effort = 'high'
      }
    } else {
      lastAgentProviderId = ''
    }
  }

  function toggleCreateTool(tool: string) {
    const value = String(tool || '').trim()
    if (!value) return
    const current = createToolSelection.value
    createToolSelection.value = current.includes(value) ? current.filter((item) => item !== value) : [...current, value]
  }

  return {
    switchOptions,
    toolOptions,
    createProviderOptions,
    createToolSelection,
    isCreateProviderField,
    isCreateToolsField,
    isCreateWebSearchField,
    isCreateThinkingField,
    isCreateReasoningEffortField,
    normalizeSwitch,
    reasoningEffortOptions,
    ensureCreateAgentSelections,
    toggleCreateTool,
  }
}
