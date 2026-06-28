import { ref } from 'vue'
import {
  getNodeInstanceLive,
  getNodeInstanceMemory,
  graphEventsStreamUrl,
  nodeInstanceLiveStreamUrl,
  readFile,
  saveFile,
} from '../api'
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

const memoryRefreshGraphEvents = new Set(['tool_call_end', 'node_message_done', 'node_output'])

export function useMemory() {
  const {
    selectedNodeId,
    memoryText,
    memoryMessages,
    memoryLiveMessage,
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

  async function loadAgentMemory() {
    if (memoryMode.value !== 'agent') return
    const nodeId = resolveSelectedTargetId()
    const graphId = currentGraphId.value || 'default'
    const requestId = ++agentLoadRequestId
    if (!nodeId) {
      if (requestId !== agentLoadRequestId || memoryMode.value !== 'agent') return
      memoryText.value = ''
      memoryMessages.value = []
      memoryLiveMessage.value = ''
      memoryTitle.value = ''
      memoryMeta.value = null
      agentImages.value = []
      return
    }
    try {
      const res = await getNodeInstanceMemory(nodeId, 20000, graphId)
      if (requestId !== agentLoadRequestId) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      memoryText.value = res.text || ''
      const baseMessages = Array.isArray((res as any)?.messages) ? ([...(res as any).messages] as any[]) : []
      memoryLiveMessage.value = String((res as any)?.live_message || '')
      memoryMessages.value = baseMessages
      memoryTitle.value = `Node ${nodeId}`
      memoryMeta.value = res.memory_path || null
      agentImages.value = []
    } catch (e: any) {
      if (requestId !== agentLoadRequestId) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      memoryText.value = ''
      memoryMessages.value = []
      memoryLiveMessage.value = ''
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
      return
    }
    try {
      const res = await getNodeInstanceLive(nodeId, graphId)
      if (requestId !== liveLoadRequestId) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      memoryLiveMessage.value = String((res as any)?.live_message || '')
    } catch {
      if (requestId !== liveLoadRequestId) return
      if (memoryMode.value !== 'agent') return
      if (resolveSelectedTargetId() !== nodeId) return
      if ((currentGraphId.value || 'default') !== graphId) return
      memoryLiveMessage.value = ''
    }
  }

  function stopAgentLiveStream() {
    if (liveEventSource) {
      liveEventSource.close()
      liveEventSource = null
    }
    liveStreamKey = ''
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
        memoryLiveMessage.value = String(payload?.live_message || '')
        const eventType = String(payload?.event_type || payload?.event?.type || '').trim()
        if (
          eventType === 'tool_call_start' ||
          eventType === 'tool_call_end' ||
          eventType === 'node_message_done' ||
          eventType === 'node_output' ||
          eventType === 'node_input'
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
    stopAgentLiveStream()
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
  }
}
