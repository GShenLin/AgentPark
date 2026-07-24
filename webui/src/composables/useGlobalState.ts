import { ref } from 'vue'
import type { ProviderInfo, GraphConfig, LatestTurnProgressSummary, LiveActivityBlock, MessageEnvelope } from '../api'

export type NodeEditorAttachment = {
  name: string
  path: string
  kind?: string
  mime?: string
}

const selectedNodeId = ref<string | null>(null)
const providers = ref<ProviderInfo[]>([])
const availableTools = ref<string[]>([])
const lastError = ref<string | null>(null)

const memoryText = ref('')
const memoryMessages = ref<MessageEnvelope[]>([])
const memoryHistoryComplete = ref(true)
const memoryLatestTurnProgressLoaded = ref(true)
const memoryLatestTurnMetadataLoaded = ref(true)
const memoryLatestTurnProgressSummary = ref<LatestTurnProgressSummary | null>(null)
const memoryLiveMessage = ref('')
const memoryThinkingMessage = ref('')
const memoryActivityMessage = ref('')
const memoryActivityBlocks = ref<LiveActivityBlock[]>([])
const memoryInteractiveSessionId = ref('')
const memoryInteractiveSending = ref(false)
const memoryTitle = ref('')
const memoryMeta = ref<string | null>(null)
const memoryMode = ref<'agent' | 'file' | 'graph'>('graph')
const memoryRefreshRequest = ref(0)
const memoryLiveRefreshRequest = ref(0)
const agentImages = ref<string[]>([])
const graphSnapshot = ref<GraphConfig | null>(null)
const graphLoadRequest = ref<GraphConfig | null>(null)
const graphNodeFocusRequest = ref<{ graphId: string; nodeId: string; nonce: number } | null>(null)
const currentGraphId = ref<string | null>('default')
const currentGraphName = ref<string | null>('default')
const currentGraphWorkingPath = ref('')
const nodeSettingsRequest = ref<{ id: string; nonce: number } | null>(null)
const nodeEditorInputText = ref('')
const nodeEditorAttachments = ref<NodeEditorAttachment[]>([])
const nodeEditorAttachmentDrafts = ref<Record<string, NodeEditorAttachment[]>>({})
const nodeTriggerInputs = ref<Record<string, string>>({})
const nodeConfigDockWidth = ref(360)

export function useGlobalState() {
  return {
    selectedNodeId,
    providers,
    availableTools,
    lastError,
    memoryText,
    memoryMessages,
    memoryHistoryComplete,
    memoryLatestTurnProgressLoaded,
    memoryLatestTurnMetadataLoaded,
    memoryLatestTurnProgressSummary,
    memoryLiveMessage,
    memoryThinkingMessage,
    memoryActivityMessage,
    memoryActivityBlocks,
    memoryInteractiveSessionId,
    memoryInteractiveSending,
    memoryTitle,
    memoryMeta,
    memoryMode,
    memoryRefreshRequest,
    memoryLiveRefreshRequest,
    agentImages,
    graphSnapshot,
    graphLoadRequest,
    graphNodeFocusRequest,
    currentGraphId,
    currentGraphName,
    currentGraphWorkingPath,
    nodeSettingsRequest,
    nodeEditorInputText,
    nodeEditorAttachments,
    nodeEditorAttachmentDrafts,
    nodeTriggerInputs,
    nodeConfigDockWidth,
  }
}
