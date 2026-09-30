import { ref } from 'vue'
import type { ProviderInfo, GraphConfig, LiveActivityBlock, MessageEnvelope } from '../api'

import type { MessageAttachment } from './messageAttachments'

export type NodeGraphDragState = {
  sourceGraphId: string
  nodeId: string
  moved: boolean
  clientX: number
  clientY: number
}

export type NodeGraphMoveRequest = {
  sourceGraphId: string
  targetGraphId: string
  nodeId: string
  nonce: number
}

const selectedNodeId = ref<string | null>(null)
const providers = ref<ProviderInfo[]>([])
const availableTools = ref<string[]>([])
const lastError = ref<string | null>(null)

const memoryText = ref('')
const memoryMessages = ref<MessageEnvelope[]>([])
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
const nodeEditorAttachments = ref<MessageAttachment[]>([])
const nodeEditorAttachmentDrafts = ref<Record<string, MessageAttachment[]>>({})
const nodeTriggerInputs = ref<Record<string, string>>({})
const nodeConfigDockWidth = ref(360)
const nodeGraphDrag = ref<NodeGraphDragState | null>(null)
const nodeGraphDropTargetId = ref('')
const nodeGraphMoveRequest = ref<NodeGraphMoveRequest | null>(null)
const nodeGraphMoveInProgress = ref(false)

export function useGlobalState() {
  return {
    selectedNodeId,
    providers,
    availableTools,
    lastError,
    memoryText,
    memoryMessages,
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
    nodeGraphDrag,
    nodeGraphDropTargetId,
    nodeGraphMoveRequest,
    nodeGraphMoveInProgress,
  }
}
