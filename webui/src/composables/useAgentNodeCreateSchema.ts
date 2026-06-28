import { computed, type Ref } from 'vue'
import type { ProviderInfo } from '../api'

type NodeFields = Record<string, any>

const defaultModeOrder = ['chat', 'image_generation', 'video_generation', 'imagechat', 'vision_understand']

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
export const GUI_AGENT_MODE = 'guiagent'
export const IMAGE_GENERATION_NODE_TYPE = 'image_generation_node'
export const IMAGE_GENERATION_MODE = 'image_generation'
export const VIDEO_GENERATION_NODE_TYPE = 'video_generation_node'
export const VIDEO_GENERATION_MODE = 'video_generation'

export function dedupeStrings(values: unknown[]): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const item of values) {
    const value = String(item ?? '').trim()
    if (!value) continue
    const key = value.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    result.push(value)
  }
  return result
}

export function normalizeMode(value: unknown) {
  return String(value ?? '').trim().toLowerCase()
}

function normalizeModeList(values: unknown): string[] {
  if (!Array.isArray(values)) return []
  return dedupeStrings(values.map((item) => normalizeMode(item)))
}

export function normalizeSwitch(value: unknown, fallback: 'enabled' | 'disabled' = 'disabled'): 'enabled' | 'disabled' {
  const text = String(value ?? '').trim().toLowerCase()
  if (['enabled', 'enable', 'on', 'true', '1', 'yes'].includes(text)) return 'enabled'
  if (['disabled', 'disable', 'off', 'false', '0', 'no'].includes(text)) return 'disabled'
  return fallback
}

export type ReasoningEffort = 'minimal' | 'low' | 'medium' | 'high' | 'xhigh'

export function providerModes(provider: Pick<ProviderInfo, 'supportmode'>) {
  const modes = normalizeModeList(provider?.supportmode)
  return modes.length ? modes : ['chat']
}

export function normalizeToolSelection(value: unknown, allowedTools: string[]): string[] {
  let list: unknown[] = []
  if (Array.isArray(value)) {
    list = value
  } else if (typeof value === 'string') {
    const raw = value.trim()
    if (!raw) {
      list = []
    } else {
      try {
        const parsed = JSON.parse(raw)
        list = Array.isArray(parsed) ? parsed : raw.split(',')
      } catch {
        list = raw.split(',')
      }
    }
  }

  const allowed = new Set(allowedTools)
  return dedupeStrings(list)
    .map((item) => item.trim())
    .filter((item) => allowed.has(item))
}

export function useAgentNodeCreateSchema(options: {
  selectedTypeId: Ref<string>
  selectedNodeFields: Ref<NodeFields>
  providers: Ref<ProviderInfo[]>
  availableTools: Ref<string[]>
}) {
  const { selectedTypeId, selectedNodeFields, providers, availableTools } = options

  const modeOptions = computed(() => {
    const discovered = providers.value.flatMap((provider) => providerModes(provider))
    const merged = dedupeStrings([...defaultModeOrder, ...discovered].map((mode) => normalizeMode(mode)))
    return merged.length ? merged : ['chat']
  })

  const toolOptions = computed(() => dedupeStrings(availableTools.value).sort((a, b) => a.localeCompare(b)))

  const createSelectedMode = computed(() => {
    if (selectedTypeId.value === GUI_AGENT_NODE_TYPE) return GUI_AGENT_MODE
    if (selectedTypeId.value === IMAGE_GENERATION_NODE_TYPE) return IMAGE_GENERATION_MODE
    if (selectedTypeId.value === VIDEO_GENERATION_NODE_TYPE) return VIDEO_GENERATION_MODE
    const mode = normalizeMode(selectedNodeFields.value.mode)
    return mode || modeOptions.value[0] || 'chat'
  })

  const createProviderOptions = computed(() => {
    const mode = createSelectedMode.value
    const ids = providers.value
      .filter((provider) => providerModes(provider).includes(mode))
      .map((provider) => String(provider.id || '').trim())
      .filter(Boolean)
    return dedupeStrings(ids).sort((a, b) => a.localeCompare(b))
  })

  const createToolSelection = computed<string[]>({
    get() {
      return normalizeToolSelection(selectedNodeFields.value.tools, toolOptions.value)
    },
    set(value) {
      selectedNodeFields.value.tools = normalizeToolSelection(value, toolOptions.value)
    },
  })

  function isCreateModeField(key: string) {
    return selectedTypeId.value === 'agent_node' && key === 'mode'
  }

  function isCreateProviderField(key: string) {
    if (key !== 'provider_id') return false
    return (
      selectedTypeId.value === 'agent_node' ||
      selectedTypeId.value === GUI_AGENT_NODE_TYPE ||
      selectedTypeId.value === IMAGE_GENERATION_NODE_TYPE ||
      selectedTypeId.value === VIDEO_GENERATION_NODE_TYPE
    )
  }

  function isCreateToolsField(key: string) {
    return selectedTypeId.value === 'agent_node' && key === 'tools'
  }

  function isCreateWebSearchField(key: string) {
    return (selectedTypeId.value === 'agent_node' || selectedTypeId.value === VIDEO_GENERATION_NODE_TYPE) && key === 'web_search'
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
      selectedTypeId.value !== GUI_AGENT_NODE_TYPE &&
      selectedTypeId.value !== IMAGE_GENERATION_NODE_TYPE &&
      selectedTypeId.value !== VIDEO_GENERATION_NODE_TYPE
    ) return

    selectedNodeFields.value.mode = createSelectedMode.value

    const providerId = String(selectedNodeFields.value.provider_id || '').trim()
    if (createProviderOptions.value.length) {
      if (!createProviderOptions.value.includes(providerId)) {
        selectedNodeFields.value.provider_id = createProviderOptions.value[0]
      }
    } else {
      selectedNodeFields.value.provider_id = ''
    }

    if (selectedTypeId.value === 'agent_node') {
      selectedNodeFields.value.tools = normalizeToolSelection(selectedNodeFields.value.tools, toolOptions.value)
      selectedNodeFields.value.web_search = normalizeSwitch(selectedNodeFields.value.web_search, 'disabled')
      selectedNodeFields.value.thinking = normalizeSwitch(selectedNodeFields.value.thinking, 'disabled')
      if (selectedNodeFields.value.reasoning_effort == null) {
        selectedNodeFields.value.reasoning_effort = 'high'
      }
    } else if (selectedTypeId.value === VIDEO_GENERATION_NODE_TYPE) {
      selectedNodeFields.value.web_search = normalizeSwitch(selectedNodeFields.value.web_search, 'disabled')
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
    modeOptions,
    toolOptions,
    createSelectedMode,
    createProviderOptions,
    createToolSelection,
    isCreateModeField,
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
