import { ref } from 'vue'
import type { ProviderInfo, GraphConfig, MessageEnvelope } from '../api'

export type NodeEditorAttachment = {
  name: string
  path: string
}

const selectedNodeId = ref<string | null>(null)
const providers = ref<ProviderInfo[]>([])
const availableTools = ref<string[]>([])
const lastError = ref<string | null>(null)

const memoryText = ref('')
const memoryMessages = ref<MessageEnvelope[]>([])
const memoryLiveMessage = ref('')
const memoryTitle = ref('')
const memoryMeta = ref<string | null>(null)
const memoryMode = ref<'agent' | 'file' | 'graph'>('graph')
const memoryRefreshRequest = ref(0)
const memoryLiveRefreshRequest = ref(0)
const agentImages = ref<string[]>([])
const graphSnapshot = ref<GraphConfig | null>(null)
const graphLoadRequest = ref<GraphConfig | null>(null)
const currentGraphId = ref<string | null>('default')
const currentGraphName = ref<string | null>('default')
const nodeSettingsRequest = ref<{ id: string; nonce: number } | null>(null)
const nodeEditorInputText = ref('')
const nodeEditorAttachments = ref<NodeEditorAttachment[]>([])
const nodeTriggerInputs = ref<Record<string, string>>({})

export function useGlobalState() {
  return {
    selectedNodeId,
    providers,
    availableTools,
    lastError,
    memoryText,
    memoryMessages,
    memoryLiveMessage,
    memoryTitle,
    memoryMeta,
    memoryMode,
    memoryRefreshRequest,
    memoryLiveRefreshRequest,
    agentImages,
    graphSnapshot,
    graphLoadRequest,
    currentGraphId,
    currentGraphName,
    nodeSettingsRequest,
    nodeEditorInputText,
    nodeEditorAttachments,
    nodeTriggerInputs,
  }
}
