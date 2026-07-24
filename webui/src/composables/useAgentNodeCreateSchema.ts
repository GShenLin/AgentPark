import { computed, type Ref } from 'vue'
import type { ProviderInfo } from '../api'

type NodeFields = Record<string, any>

export const AGENT_SUPPORT_MODE_ORDER = ['chat', 'image_generation', 'video_generation', 'audio_generation', 'imagechat', 'vision_understand'] as const

export const switchOptions = [
  { value: 'enabled', label: 'enabled' },
  { value: 'disabled', label: 'disabled' },
]

export const reasoningEffortOptions = [
  { value: 'minimal', label: 'minimal' },
  { value: 'low', label: 'low' },
  { value: 'medium', label: 'medium' },
  { value: 'high', label: 'high' },
  { value: 'xhigh', label: 'xhigh' },
]

export const GUI_AGENT_NODE_TYPE = 'gui_agent_node'
export const CODEX_NODE_TYPE = 'codex_node'
export const GUI_AGENT_MODE = 'guiagent'
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

export type ReasoningEffort = 'minimal' | 'low' | 'medium' | 'high' | 'xhigh'

export function providerModes(provider: Pick<ProviderInfo, 'supportmode'>) {
  return normalizeModeList(provider?.supportmode)
}

export function agentProviderModes(provider: Pick<ProviderInfo, 'supportmode'>): string[] {
  const supported = new Set<string>(AGENT_SUPPORT_MODE_ORDER)
  return providerModes(provider).filter((mode) => supported.has(mode))
}

export function codexProviderModes(provider: Pick<ProviderInfo, 'supportmode'>): string[] {
  return providerModes(provider).filter((mode) => mode === 'chat' || mode === 'imagechat')
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

  const createProviderOptions = computed(() => {
    const ids = providers.value
      .filter((provider) => (
        selectedTypeId.value === GUI_AGENT_NODE_TYPE
          ? providerModes(provider).includes(GUI_AGENT_MODE)
          : selectedTypeId.value === CODEX_NODE_TYPE
            ? codexProviderModes(provider).length > 0
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
      selectedTypeId.value === CODEX_NODE_TYPE ||
      selectedTypeId.value === GUI_AGENT_NODE_TYPE
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
      selectedTypeId.value !== CODEX_NODE_TYPE &&
      selectedTypeId.value !== GUI_AGENT_NODE_TYPE
    ) return

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

    if (selectedTypeId.value === 'agent_node') {
      selectedNodeFields.value.tools = normalizeToolSelection(selectedNodeFields.value.tools, toolOptions.value)
      selectedNodeFields.value.web_search = normalizeSwitch(selectedNodeFields.value.web_search, 'disabled')
      selectedNodeFields.value.thinking = normalizeSwitch(selectedNodeFields.value.thinking, 'disabled')
      if (selectedNodeFields.value.reasoning_effort == null) {
        selectedNodeFields.value.reasoning_effort = 'high'
      }
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
