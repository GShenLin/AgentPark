import { ref } from 'vue'
import {
  getNodeInstanceLive,
  getNodeInstanceMemory,
  graphEventsStreamUrl,
  nodeInstanceLiveStreamUrl,
  readFile,
  saveFile,
  sendNodeInteractiveInput,
  type MessageEnvelope,
  type MemoryHistoryMode,
} from '../api'
import { formatLiveActivity } from '../liveActivity'
import { useGlobalState } from './useGlobalState'

const isSaving = ref(false)
const memoryAutoScroll = ref(true)
let agentLoadRequestId = 0
let liveLoadRequestId = 0
let liveEventSource: EventSource | null = null
let liveStreamKey = ''
let graphEventSource: EventSource | null = null
let graphEventStreamKey = ''
let graphMemoryRefreshTimer: number | null = null
let pendingCommittedLiveText = ''
let pendingCommittedLiveTraceId = ''

const memoryRefreshGraphEvents = new Set(['tool_call_end', 'node_message_done', 'node_output', 'node_error'])

function messageText(message: MessageEnvelope): string {
  const parts = Array.isArray(message?.parts) ? message.parts : []
  return parts
    .filter((part) => part && part.type === 'text')
    .map((part) => String((part as { text?: unknown }).text || ''))
    .join('\n')
    .trim()
}

function messagesContainCommittedLive(messages: MessageEnvelope[], text: string, traceId: string): boolean {
  const safeTraceId = String(traceId || '').trim()
  if (safeTraceId && messages.some((message) => String(message?.trace_id || '').trim() === safeTraceId)) return true
  const safeText = String(text || '').trim()
  if (!safeText) return false
  return messages.some((message) => {
    const role = String(message?.role || '').trim().toLowerCase()
    return role !== 'user' && messageText(message) === safeText
  })
}

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
    memoryHistoryComplete,
    memoryLatestTurnProgressLoaded,
    memoryLatestTurnMetadataLoaded,
    memoryLatestTurnProgressSummary,
    memoryLiveMessage,
    memoryThinkingMessage,
    memoryActivityMessage,
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

  async function loadAgentMemory(options: { historyMode?: MemoryHistoryMode } = {}) {
    if (memoryMode.value !== 'agent') return
    const nodeId = resolveSelectedTargetId()
    const graphId = currentGraphId.value || 'default'
    const requestId = ++agentLoadRequestId
    if (!nodeId) {
      if (requestId !== agentLoadRequestId || memoryMode.value !== 'agent') return
      memoryText.value = ''
      memoryMessages.value = []
      memoryHistoryComplete.value = true
      memoryLatestTurnProgressLoaded.value = true
      memoryLatestTurnMetadataLoaded.value = true
      memoryLatestTurnProgressSummary.value = null
      memoryLiveMessage.value = ''
      memoryThinkingMessage.value = ''
      memoryActivityMessage.value = ''
      clearPendingCommittedLive()
      memoryInteractiveSessionId.value = ''
      memoryTitle.value = ''
      memoryMeta.value = null
      agentImages.value = []
      return
    }
    try {
      const historyMode = options.historyMode || (memoryHistoryComplete.value ? 'all' : 'latest_turn')
      const res = await getNodeInstanceMemory(nodeId, 20000, graphId, historyMode)
      if (requestId !== agentLoadRequestId) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      const baseMessages = Array.isArray((res as any)?.messages) ? ([...(res as any).messages] as any[]) : []
      const isLazySection = historyMode === 'latest_turn_progress' || historyMode === 'latest_turn_metadata'
      if (isLazySection) {
        const merged = new Map<string, MessageEnvelope>()
        for (const message of [...memoryMessages.value, ...baseMessages]) {
          const key = String(message?.id || `${message?.role || ''}-${message?.created_at || ''}`)
          merged.set(key, message)
        }
        memoryMessages.value = [...merged.values()].sort((left, right) =>
          String(left?.created_at || '').localeCompare(String(right?.created_at || '')),
        )
      } else {
        memoryText.value = res.text || ''
        memoryMessages.value = baseMessages
      }
      memoryHistoryComplete.value = res.history_complete !== false
      memoryLatestTurnProgressSummary.value = res.latest_turn_progress_summary || null
      if (historyMode === 'latest_turn') {
        memoryLatestTurnProgressLoaded.value = false
        memoryLatestTurnMetadataLoaded.value = false
      } else if (historyMode === 'latest_turn_progress') {
        memoryLatestTurnProgressLoaded.value = true
      } else if (historyMode === 'latest_turn_metadata') {
        memoryLatestTurnMetadataLoaded.value = true
      } else if (historyMode === 'all') {
        memoryLatestTurnProgressLoaded.value = true
        memoryLatestTurnMetadataLoaded.value = true
      }
      if (messagesContainCommittedLive(baseMessages, pendingCommittedLiveText, pendingCommittedLiveTraceId)) {
        clearPendingCommittedLive()
        memoryLiveMessage.value = ''
      } else {
        const nextLiveMessage = String((res as any)?.live_message || '')
        memoryLiveMessage.value = nextLiveMessage || pendingCommittedLiveText
      }
      memoryThinkingMessage.value = String((res as any)?.thinking_message || '')
      memoryActivityMessage.value = ''
      memoryTitle.value = `Node ${nodeId}`
      memoryMeta.value = res.memory_path || null
      agentImages.value = []
    } catch (e: any) {
      if (requestId !== agentLoadRequestId) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      if (options.historyMode === 'latest_turn_progress' || options.historyMode === 'latest_turn_metadata') {
        lastError.value = String(e?.message || e)
        return
      }
      memoryText.value = ''
      memoryMessages.value = []
      memoryHistoryComplete.value = true
      memoryLatestTurnProgressLoaded.value = true
      memoryLatestTurnMetadataLoaded.value = true
      memoryLatestTurnProgressSummary.value = null
      memoryLiveMessage.value = ''
      memoryThinkingMessage.value = ''
      memoryActivityMessage.value = ''
      clearPendingCommittedLive()
      memoryInteractiveSessionId.value = ''
      memoryTitle.value = `Node ${nodeId}`
      memoryMeta.value = String(e?.message || e)
      agentImages.value = []
    }
  }

  async function loadAgentLiveMessage() {
    if (memoryMode.value !== 'agent') return
    const nodeId = resolveSelectedTargetId()
    const graphId = currentGraphId.value || 'default'
    const requestId = ++liveLoadRequestId
    if (!nodeId) {
      if (requestId !== liveLoadRequestId || memoryMode.value !== 'agent') return
      memoryLiveMessage.value = ''
      memoryThinkingMessage.value = ''
      memoryActivityMessage.value = ''
      clearPendingCommittedLive()
      return
    }
    try {
      const res = await getNodeInstanceLive(nodeId, graphId)
      if (requestId !== liveLoadRequestId) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      const nextLiveMessage = String((res as any)?.live_message || '')
      memoryLiveMessage.value = nextLiveMessage || pendingCommittedLiveText
      memoryThinkingMessage.value = String((res as any)?.thinking_message || '')
    } catch {
      if (requestId !== liveLoadRequestId) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      memoryLiveMessage.value = ''
      memoryThinkingMessage.value = ''
      memoryActivityMessage.value = ''
      clearPendingCommittedLive()
    }
  }

  function stopAgentLiveStream() {
    if (liveEventSource) {
      liveEventSource.close()
      liveEventSource = null
    }
    liveStreamKey = ''
    memoryInteractiveSessionId.value = ''
    clearPendingCommittedLive()
    stopAgentGraphEventStream()
    clearScheduledGraphMemoryRefresh()
  }

  function clearScheduledGraphMemoryRefresh() {
    if (graphMemoryRefreshTimer != null) {
      window.clearTimeout(graphMemoryRefreshTimer)
      graphMemoryRefreshTimer = null
    }
  }

  function scheduleGraphMemoryRefresh() {
    if (graphMemoryRefreshTimer != null) return
    graphMemoryRefreshTimer = window.setTimeout(() => {
      graphMemoryRefreshTimer = null
      if (memoryMode.value !== 'agent') return
      if (!resolveSelectedTargetId()) return
      memoryRefreshRequest.value += 1
    }, 75)
  }

  function stopAgentGraphEventStream() {
    if (graphEventSource) {
      graphEventSource.close()
      graphEventSource = null
    }
    graphEventStreamKey = ''
  }

  function graphEventTargetsNode(payload: Record<string, unknown>, nodeId: string) {
    const target = String(nodeId || '').trim()
    if (!target) return false
    const candidates = [payload.node_instance_id, payload.node_id, payload.from_id]
    return candidates.some((item) => String(item || '').trim() === target)
  }

  function startAgentGraphEventStream(nodeId: string, graphId: string) {
    const streamKey = `${graphId}:${nodeId}`
    if (graphEventSource && graphEventStreamKey === streamKey) return
    stopAgentGraphEventStream()

    const source = new EventSource(graphEventsStreamUrl(graphId))
    graphEventSource = source
    graphEventStreamKey = streamKey
    source.onmessage = (event) => {
      if (graphEventSource !== source) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      try {
        const payload = JSON.parse(String(event.data || '{}')) as Record<string, unknown>
        const eventName = String(payload?.event || '').trim()
        if (memoryRefreshGraphEvents.has(eventName) && graphEventTargetsNode(payload, nodeId)) {
          scheduleGraphMemoryRefresh()
        }
      } catch {
        // Ignore malformed graph events; the next valid event will correct the view.
      }
    }
    source.onerror = () => {
      if (graphEventSource !== source) return
      if (
        memoryMode.value !== 'agent' ||
        resolveSelectedTargetId() !== nodeId ||
        (currentGraphId.value || 'default') !== graphId
      ) {
        source.close()
        graphEventSource = null
        graphEventStreamKey = ''
      }
    }
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
      clearPendingCommittedLive()
      memoryInteractiveSessionId.value = ''
      return
    }
    const streamKey = `${graphId}:${nodeId}`
    if (liveEventSource && liveStreamKey === streamKey) {
      startAgentGraphEventStream(nodeId, graphId)
      return
    }
    stopAgentLiveStream()
    startAgentGraphEventStream(nodeId, graphId)

    const source = new EventSource(nodeInstanceLiveStreamUrl(nodeId, graphId))
    liveEventSource = source
    liveStreamKey = streamKey
    source.onmessage = (event) => {
      if (liveEventSource !== source) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      try {
        const payload = JSON.parse(String(event.data || '{}'))
        const eventType = String(payload?.event_type || payload?.event?.type || '').trim()
        const eventData = payload?.event && typeof payload.event === 'object'
          ? (payload.event as Record<string, unknown>)
          : null
        const nextLiveMessage = String(payload?.live_message || '')
        const nextThinkingMessage = String(payload?.thinking_message || '')
        const nextActivityMessage = formatLiveActivity(eventType, eventData)
        memoryThinkingMessage.value = nextThinkingMessage
        if (eventType === 'node_message_done' || eventType === 'node_output') {
          rememberCommittedLiveText(
            String(eventData?.text || nextLiveMessage || memoryLiveMessage.value || ''),
            String(payload?.trace_id || eventData?.trace_id || ''),
          )
          if (pendingCommittedLiveText) memoryLiveMessage.value = pendingCommittedLiveText
          memoryThinkingMessage.value = ''
          memoryActivityMessage.value = ''
        } else if (nextLiveMessage || !pendingCommittedLiveText) {
          memoryLiveMessage.value = nextLiveMessage
        }
        if (nextActivityMessage) memoryActivityMessage.value = nextActivityMessage
        else if (eventType === 'server_tool_activity') memoryActivityMessage.value = ''
        // Persistent session_id (set by server on stdin_ready, survives text update races)
        const persistentSessionId = String(payload?.interactive_session_id || '').trim()
        if (persistentSessionId) {
          memoryInteractiveSessionId.value = persistentSessionId
        }
        // Transient events also set/clear session_id
        if (eventType === 'stdin_ready' && eventData) {
          const sid = String(eventData?.session_id || '').trim()
          if (sid) memoryInteractiveSessionId.value = sid
        } else if (eventType === 'stdin_closed' || eventType === 'node_message_done') {
          const closedSessionId = String(eventData?.session_id || '').trim()
          if (!closedSessionId || closedSessionId === memoryInteractiveSessionId.value) {
            memoryInteractiveSessionId.value = ''
          }
        }
        if (
          eventType === 'server_tool_activity' ||
          eventType === 'tool_call_start' ||
          eventType === 'tool_call_end' ||
          eventType === 'node_message_done' ||
          eventType === 'node_output' ||
          eventType === 'node_input' ||
          eventType === 'stdin_ready' ||
          eventType === 'stdin_closed'
        ) {
          memoryRefreshRequest.value += 1
        }
      } catch {
        // Ignore malformed stream events; the next valid event will correct the view.
      }
    }
    source.onerror = () => {
      if (liveEventSource !== source) return
      if (memoryMode.value !== 'agent' || resolveSelectedTargetId() !== nodeId || (currentGraphId.value || 'default') !== graphId) {
        source.close()
        liveEventSource = null
        liveStreamKey = ''
      }
    }
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
    agentLoadRequestId += 1
    liveLoadRequestId += 1
    memoryInteractiveSessionId.value = ''
    stopAgentLiveStream()
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
    sendInteractiveInput,
  }
}
