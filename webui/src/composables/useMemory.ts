import { ref } from 'vue'
import { nodeOpenMarker } from '../nodeOpenDiagnostics'
import {
  getNodeInstanceLive,
  getNodeInstanceMemory,
  readFile,
  saveFile,
  sendNodeInteractiveInput,
} from '../api'
import { formatLiveActivity } from '../liveActivity'
import {
  isLiveCompletionEvent,
  LIVE_OUTPUT_COMMITTED_EVENT,
  LIVE_STREAM_FINISHED_EVENT,
  resolveLiveCompletionHandoff,
} from '../liveCompletionHandoff'
import { useGlobalState } from './useGlobalState'
import { consumeAudioStreamEvents } from './streamingAudioPlayback'
import { subscribeAppEvents } from './useAppEventStream'
import { classifyLiveStreamFrame } from '../eventStreamProtocol'
import { SELECTION_REQUEST_SETTLE_MS } from '../selectionRequestPolicy'
import {
  ConversationRequestCoordinator,
  type ConversationRequestScope,
} from '../conversationRequestCoordinator'

const isSaving = ref(false)
const memoryAutoScroll = ref(true)
let liveStreamKey = ''
let liveStreamVersion = 0
let stopAgentEvents: (() => void) | null = null
let graphMemoryRefreshTimer: number | null = null
let selectionLoadTimer: number | null = null
let memorySelectionGeneration = 0
let graphMemoryRefreshInFlightGeneration = -1
let graphMemoryRefreshMode: 'completion' | 'progress' | null = null
let baseMemoryAbortController: AbortController | null = null
const memoryRequests = new ConversationRequestCoordinator()
type LiveRefreshState = { promise: Promise<void>; controller: AbortController }
const liveRefreshStates = new Map<string, LiveRefreshState>()
let pendingCommittedLiveText = ''
let pendingCommittedLiveTraceId = ''

const memoryRefreshHistoryModeByGraphEvent = new Map<string, 'completion' | 'progress'>([
  ['node_progress_updated', 'progress'],
  [LIVE_STREAM_FINISHED_EVENT, 'completion'],
  [LIVE_OUTPUT_COMMITTED_EVENT, 'completion'],
  ['node_error', 'completion'],
])

function rememberCommittedLiveText(text: string, traceId: string) {
  const safeText = String(text || '').trim()
  if (!safeText) return
  pendingCommittedLiveText = safeText
  pendingCommittedLiveTraceId = String(traceId || '').trim()
}

function clearPendingCommittedLive() {
  pendingCommittedLiveText = ''
  pendingCommittedLiveTraceId = ''
}

export function useMemory() {
  const {
    selectedNodeId,
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
    lastError,
    currentGraphId,
  } = useGlobalState()

  function resolveSelectedTargetId(): string {
    const nodeId = String(selectedNodeId.value || '').trim()
    return nodeId || ''
  }

  function conversationSelectionKey(graphId: string, nodeId: string) {
    return `${graphId}:${nodeId}`
  }

  function clearMissingAgentSelection() {
    memoryText.value = ''
    memoryMessages.value = []
    memoryLiveMessage.value = ''
    memoryThinkingMessage.value = ''
    memoryActivityMessage.value = ''
    memoryActivityBlocks.value = []
    clearPendingCommittedLive()
    memoryInteractiveSessionId.value = ''
    memoryTitle.value = ''
    memoryMeta.value = null
    agentImages.value = []
  }

  async function loadAgentMemoryOnce(
    signal: AbortSignal,
    generation: number,
    requestScope: ConversationRequestScope,
  ) {
    if (memoryMode.value !== 'agent') return
    const nodeId = resolveSelectedTargetId()
    const graphId = currentGraphId.value || 'default'
    if (!nodeId) {
      if (generation !== memorySelectionGeneration || memoryMode.value !== 'agent') return
      clearMissingAgentSelection()
      return
    }
    try {
      const res = await getNodeInstanceMemory(nodeId, 20000, graphId, 'conversation', { signal })
      if (signal.aborted || generation !== memorySelectionGeneration) return
      if (!memoryRequests.isActiveScope(requestScope)) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      const baseMessages = Array.isArray((res as any)?.messages) ? ([...(res as any).messages] as any[]) : []
      memoryText.value = res.text || ''
      memoryMessages.value = baseMessages
      const committedLive = resolveLiveCompletionHandoff(
        baseMessages,
        pendingCommittedLiveText,
        pendingCommittedLiveTraceId,
      )
      if (committedLive.status === 'committed') {
        clearPendingCommittedLive()
        memoryLiveMessage.value = ''
      } else {
        const nextLiveMessage = String((res as any)?.live_message || '')
        memoryLiveMessage.value = nextLiveMessage || pendingCommittedLiveText
      }
      memoryThinkingMessage.value = String((res as any)?.thinking_message || '')
      memoryActivityMessage.value = ''
      memoryActivityBlocks.value = Array.isArray((res as any)?.activity_blocks) ? (res as any).activity_blocks : []
      memoryTitle.value = `Node ${nodeId}`
      memoryMeta.value = res.memory_path || null
      agentImages.value = []
      nodeOpenMarker(graphId, nodeId)?.('memory_applied', {
        messages: baseMessages.length, text_chars: memoryText.value.length,
        live_chars: memoryLiveMessage.value.length,
      })
    } catch (e: any) {
      if (signal.aborted || generation !== memorySelectionGeneration) return
      if (!memoryRequests.isActiveScope(requestScope)) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      memoryText.value = ''
      memoryMessages.value = []
      memoryLiveMessage.value = ''
      memoryThinkingMessage.value = ''
      memoryActivityMessage.value = ''
      memoryActivityBlocks.value = []
      clearPendingCommittedLive()
      memoryInteractiveSessionId.value = ''
      memoryTitle.value = `Node ${nodeId}`
      memoryMeta.value = String(e?.message || e)
      agentImages.value = []
    }
  }

  async function loadAgentMemory() {
    if (memoryMode.value !== 'agent') return
    const nodeId = resolveSelectedTargetId()
    const graphId = currentGraphId.value || 'default'
    if (!nodeId) {
      stopLoading()
      clearMissingAgentSelection()
      return
    }
    const generation = memorySelectionGeneration
    const selectionKey = conversationSelectionKey(graphId, nodeId)
    const requestScope = memoryRequests.begin(selectionKey, 'conversation')
    const controller = new AbortController()
    baseMemoryAbortController?.abort()
    baseMemoryAbortController = controller
    try {
      await loadAgentMemoryOnce(controller.signal, generation, requestScope)
    } finally {
      if (baseMemoryAbortController === controller) baseMemoryAbortController = null
    }
  }

  async function loadAgentLiveMessageOnce(
    nodeId: string,
    graphId: string,
    signal: AbortSignal,
    generation: number,
  ) {
    if (!nodeId) {
      if (generation !== memorySelectionGeneration || memoryMode.value !== 'agent') return
      memoryLiveMessage.value = ''
      memoryThinkingMessage.value = ''
      memoryActivityMessage.value = ''
      memoryActivityBlocks.value = []
      clearPendingCommittedLive()
      return
    }
    try {
      const res = await getNodeInstanceLive(nodeId, graphId, { signal })
      if (signal.aborted || generation !== memorySelectionGeneration) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      const nextLiveMessage = String((res as any)?.live_message || '')
      liveStreamVersion = Number((res as any)?.version || 0)
      memoryLiveMessage.value = nextLiveMessage || pendingCommittedLiveText
      memoryThinkingMessage.value = String((res as any)?.thinking_message || '')
      memoryActivityBlocks.value = Array.isArray((res as any)?.activity_blocks) ? (res as any).activity_blocks : []
      nodeOpenMarker(graphId, nodeId)?.('live_applied', { live_chars: memoryLiveMessage.value.length, thinking_chars: memoryThinkingMessage.value.length })
    } catch {
      if (signal.aborted || generation !== memorySelectionGeneration) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      memoryLiveMessage.value = ''
      memoryThinkingMessage.value = ''
      memoryActivityMessage.value = ''
      memoryActivityBlocks.value = []
      clearPendingCommittedLive()
    }
  }

  async function loadAgentLiveMessage() {
    if (memoryMode.value !== 'agent') return
    const nodeId = resolveSelectedTargetId()
    const graphId = currentGraphId.value || 'default'
    const generation = memorySelectionGeneration
    if (!nodeId) {
      const controller = new AbortController()
      await loadAgentLiveMessageOnce(nodeId, graphId, controller.signal, generation)
      return
    }

    const key = `${graphId}:${nodeId}`
    const existing = liveRefreshStates.get(key)
    if (existing) {
      await existing.promise
      return
    }

    const controller = new AbortController()
    const state = {
      controller,
      promise: loadAgentLiveMessageOnce(nodeId, graphId, controller.signal, generation),
    } as LiveRefreshState
    liveRefreshStates.set(key, state)
    try {
      await state.promise
    } finally {
      if (liveRefreshStates.get(key) === state) liveRefreshStates.delete(key)
    }
  }

  function stopAgentLiveStream() {
    stopAgentEvents?.()
    stopAgentEvents = null
    liveStreamKey = ''
    liveStreamVersion = 0
    for (const state of liveRefreshStates.values()) state.controller.abort()
    liveRefreshStates.clear()
    memoryInteractiveSessionId.value = ''
    clearPendingCommittedLive()
    clearScheduledGraphMemoryRefresh()
  }

  function clearScheduledGraphMemoryRefresh() {
    if (graphMemoryRefreshTimer != null) {
      window.clearTimeout(graphMemoryRefreshTimer)
      graphMemoryRefreshTimer = null
    }
    graphMemoryRefreshMode = null
  }

  function scheduleGraphMemoryRefresh(mode: 'completion' | 'progress') {
    const generation = memorySelectionGeneration
    if (graphMemoryRefreshMode !== 'completion') graphMemoryRefreshMode = mode
    if (mode === 'completion' && graphMemoryRefreshTimer != null) {
      window.clearTimeout(graphMemoryRefreshTimer)
      graphMemoryRefreshTimer = null
    }
    if (graphMemoryRefreshTimer != null || graphMemoryRefreshInFlightGeneration === generation) return
    const delay = graphMemoryRefreshMode === 'completion' ? 75 : 500
    graphMemoryRefreshTimer = window.setTimeout(async () => {
      graphMemoryRefreshTimer = null
      if (generation !== memorySelectionGeneration) return
      if (memoryMode.value !== 'agent') return
      if (!resolveSelectedTargetId()) return
      const historyMode = graphMemoryRefreshMode
      graphMemoryRefreshMode = null
      if (!historyMode) return
      graphMemoryRefreshInFlightGeneration = generation
      try {
        await loadAgentMemory()
      } finally {
        if (graphMemoryRefreshInFlightGeneration === generation) {
          graphMemoryRefreshInFlightGeneration = -1
        }
        if (generation === memorySelectionGeneration && graphMemoryRefreshMode) {
          scheduleGraphMemoryRefresh(graphMemoryRefreshMode)
        }
      }
    }, delay)
  }

  function graphEventTargetsNode(payload: Record<string, unknown>, nodeId: string) {
    const target = String(nodeId || '').trim()
    if (!target) return false
    const candidates = [payload.node_instance_id, payload.node_id, payload.from_id]
    return candidates.some((item) => String(item || '').trim() === target)
  }

  function consumeLivePayload(payload: Record<string, any>) {
    const decision = classifyLiveStreamFrame(payload, liveStreamVersion)
    const { version, streamType } = decision.frame
    if (decision.status === 'stale') return
    if (decision.status === 'gap') {
      void loadAgentLiveMessage()
      return
    }
    liveStreamVersion = version
    consumeAudioStreamEvents(payload.media_chunks)
    const eventType = String(payload.event_type || payload.event?.type || '').trim()
    const eventData = payload.event && typeof payload.event === 'object'
      ? (payload.event as Record<string, unknown>)
      : null
    const nextLiveMessage = streamType === 'delta'
      ? memoryLiveMessage.value + String(payload.live_delta || '')
      : String(payload.live_message || '')
    const nextThinkingMessage = streamType === 'delta'
      ? memoryThinkingMessage.value + String(payload.thinking_delta || '')
      : String(payload.thinking_message || '')
    const nextActivityMessage = formatLiveActivity(eventType, eventData)
    if (Array.isArray(payload.activity_blocks)) memoryActivityBlocks.value = payload.activity_blocks
    memoryThinkingMessage.value = nextThinkingMessage
    if (isLiveCompletionEvent(eventType)) {
      const handoff = resolveLiveCompletionHandoff(
        memoryMessages.value,
        String(eventData?.text || nextLiveMessage || memoryLiveMessage.value || ''),
        String(payload.trace_id || eventData?.trace_id || ''),
      )
      if (handoff.status === 'committed') {
        clearPendingCommittedLive()
        memoryLiveMessage.value = ''
      } else if (handoff.status === 'pending') {
        rememberCommittedLiveText(handoff.text, handoff.traceId)
        memoryLiveMessage.value = handoff.text
      }
      memoryThinkingMessage.value = ''
      memoryActivityMessage.value = ''
      memoryActivityBlocks.value = []
    } else if (nextLiveMessage || !pendingCommittedLiveText) {
      memoryLiveMessage.value = nextLiveMessage
    }
    if (nextActivityMessage) memoryActivityMessage.value = nextActivityMessage
    else if (eventType === 'server_tool_activity') memoryActivityMessage.value = ''
    const persistentSessionId = String(payload.interactive_session_id || '').trim()
    if (persistentSessionId) memoryInteractiveSessionId.value = persistentSessionId
    if (eventType === 'stdin_ready' && eventData) {
      const sessionId = String(eventData.session_id || '').trim()
      if (sessionId) memoryInteractiveSessionId.value = sessionId
    } else if (eventType === 'stdin_closed' || eventType === 'node_message_done') {
      const closedSessionId = String(eventData?.session_id || '').trim()
      if (!closedSessionId || closedSessionId === memoryInteractiveSessionId.value) {
        memoryInteractiveSessionId.value = ''
      }
    }
    if (isLiveCompletionEvent(eventType)) scheduleGraphMemoryRefresh('completion')
  }

  function startAgentLiveStream() {
    if (memoryMode.value !== 'agent') {
      stopAgentLiveStream()
      return
    }
    const nodeId = resolveSelectedTargetId()
    const graphId = currentGraphId.value || 'default'
    if (!nodeId) {
      stopAgentLiveStream()
      memoryLiveMessage.value = ''
      memoryThinkingMessage.value = ''
      memoryActivityBlocks.value = []
      clearPendingCommittedLive()
      memoryInteractiveSessionId.value = ''
      return
    }
    const streamKey = `${graphId}:${nodeId}`
    if (stopAgentEvents && liveStreamKey === streamKey) return
    stopAgentLiveStream()
    liveStreamKey = streamKey
    stopAgentEvents = subscribeAppEvents((payload) => {
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      if (String(payload.event || '').trim() === 'stream_gap') {
        void loadAgentLiveMessage()
        scheduleGraphMemoryRefresh('completion')
        return
      }
      if (String(payload.graph_id || '').trim() !== graphId || !graphEventTargetsNode(payload, nodeId)) return
      const eventName = String(payload.event || '').trim()
      if (eventName === 'node_live') {
        if (payload.live && typeof payload.live === 'object') {
          consumeLivePayload(payload.live as Record<string, any>)
        }
        return
      }
      const historyMode = memoryRefreshHistoryModeByGraphEvent.get(eventName)
      if (historyMode) scheduleGraphMemoryRefresh(historyMode)
    })
    void loadAgentLiveMessage()
  }

  async function onFileSelected(file: { name: string; path: string }) {
    memoryMode.value = 'file'
    memoryTitle.value = file.name
    memoryMeta.value = file.path
    memoryText.value = 'Loading...'
    memoryMessages.value = []
    memoryLiveMessage.value = ''
    memoryThinkingMessage.value = ''
    clearPendingCommittedLive()
    memoryInteractiveSessionId.value = ''
    try {
      const res = await readFile(file.path)
      memoryText.value = res.content
    } catch (e: any) {
      memoryText.value = `Error reading file: ${e.message}`
    }
  }

  async function saveCurrentFile() {
    if (memoryMode.value !== 'file' || !memoryMeta.value) return
    isSaving.value = true
    try {
      await saveFile(memoryMeta.value, memoryText.value)
    } catch (e: any) {
      lastError.value = `Failed to save file: ${e.message}`
    } finally {
      isSaving.value = false
    }
  }

  function requestMemoryRefresh() {
    memoryRefreshRequest.value += 1
  }

  function requestMemoryLiveRefresh() {
    memoryLiveRefreshRequest.value += 1
  }

  function stopLoading() {
    memorySelectionGeneration += 1
    memoryRequests.deactivate()
    if (selectionLoadTimer != null) {
      window.clearTimeout(selectionLoadTimer)
      selectionLoadTimer = null
    }
    baseMemoryAbortController?.abort()
    baseMemoryAbortController = null
    memoryInteractiveSessionId.value = ''
    stopAgentLiveStream()
  }

  function beginAgentSelection() {
    nodeOpenMarker(currentGraphId.value || 'default', resolveSelectedTargetId())?.('selection_watch')
    stopLoading()
    if (memoryMode.value !== 'agent') return
    const nodeId = resolveSelectedTargetId()
    const graphId = currentGraphId.value || 'default'
    if (nodeId) memoryRequests.activate(conversationSelectionKey(graphId, nodeId))
    memoryText.value = ''
    memoryMessages.value = []
    memoryLiveMessage.value = ''
    memoryThinkingMessage.value = ''
    memoryActivityMessage.value = ''
    memoryActivityBlocks.value = []
    memoryInteractiveSessionId.value = ''
    memoryTitle.value = nodeId ? `Node ${nodeId}` : ''
    memoryMeta.value = null
    agentImages.value = []
    const generation = memorySelectionGeneration
    selectionLoadTimer = window.setTimeout(() => {
      selectionLoadTimer = null
      if (generation !== memorySelectionGeneration) return
      if (memoryMode.value !== 'agent' || !resolveSelectedTargetId()) return
      startAgentLiveStream()
      void loadAgentMemory()
    }, SELECTION_REQUEST_SETTLE_MS)
  }

  async function sendInteractiveInput(
    text: string,
    options: { appendNewline?: boolean; sendEof?: boolean; sendCtrlC?: boolean } = {},
  ) {
    const nodeId = resolveSelectedTargetId()
    const graphId = currentGraphId.value || 'default'
    const sessionId = String(memoryInteractiveSessionId.value || '').trim()
    if (!nodeId || !sessionId) return false
    memoryInteractiveSending.value = true
    try {
      await sendNodeInteractiveInput(nodeId, graphId, {
        session_id: sessionId,
        text: String(text || ''),
        append_newline: options.appendNewline !== false,
        send_eof: !!options.sendEof,
        send_ctrl_c: !!options.sendCtrlC,
      })
      return true
    } catch (e: any) {
      lastError.value = String(e?.message || e)
      return false
    } finally {
      memoryInteractiveSending.value = false
    }
  }

  return {
    isSaving,
    memoryAutoScroll,
    loadAgentMemory,
    loadAgentLiveMessage,
    startAgentLiveStream,
    stopAgentLiveStream,
    requestMemoryRefresh,
    requestMemoryLiveRefresh,
    onFileSelected,
    saveCurrentFile,
    stopLoading,
    beginAgentSelection,
    sendInteractiveInput,
  }
}
