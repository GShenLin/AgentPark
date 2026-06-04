import { ref } from 'vue'
import { getNodeInstanceMemory, readFile, saveFile } from '../api'
import { useGlobalState } from './useGlobalState'

export function useMemory() {
  const {
    selectedNodeId,
    memoryText,
    memoryMessages,
    memoryTitle,
    memoryMeta,
    memoryMode,
    agentImages,
    lastError,
    currentGraphId,
  } = useGlobalState()

  const isSaving = ref(false)
  const memoryAutoScroll = ref(true)
  let pollMemoryTimer: number | null = null
  let pollSessionId = 0
  let agentLoadRequestId = 0

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
      const state = String((res as any)?.state || '').trim().toLowerCase()
      const liveText = String((res as any)?.last_message || '').trim()
      const canShowLive = state === 'working' || state === 'idle'
      if (canShowLive && liveText) {
        const lastMsg = baseMessages.length > 0 ? baseMessages[baseMessages.length - 1] : null
        const lastParts = Array.isArray((lastMsg as any)?.parts) ? ((lastMsg as any).parts as any[]) : []
        const lastText = lastParts
          .filter((part) => String((part as any)?.type || '').toLowerCase() === 'text')
          .map((part) => String((part as any)?.text || ''))
          .join('\n')
          .trim()
        if (!lastText || lastText !== liveText) {
          baseMessages.push({
            id: `__live__${nodeId}`,
            role: 'assistant',
            created_at: '',
            parts: [{ type: 'text', text: liveText }],
          })
        }
      }
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
      memoryTitle.value = `Node ${nodeId}`
      memoryMeta.value = String(e?.message || e)
      agentImages.value = []
    }
  }

  async function onFileSelected(file: { name: string; path: string }) {
    memoryMode.value = 'file'
    memoryTitle.value = file.name
    memoryMeta.value = file.path
    memoryText.value = 'Loading...'
    memoryMessages.value = []
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

  function startPolling() {
    stopPolling()
    const sessionId = ++pollSessionId
    const runTick = async () => {
      if (sessionId !== pollSessionId) return
      if (memoryMode.value === 'agent') {
        await loadAgentMemory()
      }
      if (sessionId !== pollSessionId) return
      pollMemoryTimer = window.setTimeout(runTick, 100)
    }
    pollMemoryTimer = window.setTimeout(runTick, 100)
  }

  function stopPolling() {
    if (pollMemoryTimer != null) {
      window.clearTimeout(pollMemoryTimer)
      pollMemoryTimer = null
    }
    pollSessionId += 1
    agentLoadRequestId += 1
  }

  return {
    isSaving,
    memoryAutoScroll,
    loadAgentMemory,
    onFileSelected,
    saveCurrentFile,
    startPolling,
    stopPolling,
  }
}
