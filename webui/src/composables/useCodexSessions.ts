import { ref } from 'vue'
import {
  listCodexSessions,
  selectCodexSession,
  type CodexSessionListResponse,
} from '../api'

type CodexSessionSelectionState = CodexSessionListResponse & { ok?: boolean }

export function useCodexSessions(options: {
  getNodeId: () => string
  getGraphId: () => string
  isEnabled?: () => boolean
  onAfterSelect?: (state: CodexSessionSelectionState) => void | Promise<void>
  onError?: (error: unknown) => void
}) {
  const codexSessionState = ref<CodexSessionListResponse | null>(null)
  const codexSessionLoading = ref(false)
  let codexSessionRequestGeneration = 0

  function currentSelection() {
    return {
      nodeId: String(options.getNodeId() || '').trim(),
      graphId: String(options.getGraphId() || 'default').trim() || 'default',
    }
  }

  function isStillCurrent(nodeId: string, graphId: string) {
    const current = currentSelection()
    return current.nodeId === nodeId && current.graphId === graphId
  }

  function resetCodexSessions() {
    codexSessionRequestGeneration += 1
    codexSessionState.value = null
    codexSessionLoading.value = false
  }

  async function refreshCodexSessions() {
    const { nodeId, graphId } = currentSelection()
    const generation = ++codexSessionRequestGeneration
    if (!nodeId || (options.isEnabled && !options.isEnabled())) {
      codexSessionState.value = null
      return
    }
    codexSessionLoading.value = true
    try {
      const state = await listCodexSessions(nodeId, graphId)
      if (generation !== codexSessionRequestGeneration) return
      if (!isStillCurrent(nodeId, graphId)) return
      codexSessionState.value = state.supported ? state : null
    } catch {
      if (generation === codexSessionRequestGeneration) codexSessionState.value = null
    } finally {
      if (generation === codexSessionRequestGeneration) codexSessionLoading.value = false
    }
  }

  async function chooseCodexSession(sessionId: string) {
    const { nodeId, graphId } = currentSelection()
    if (!nodeId || codexSessionLoading.value) return
    if (options.isEnabled && !options.isEnabled()) return
    codexSessionLoading.value = true
    try {
      const state = await selectCodexSession(nodeId, sessionId, graphId)
      if (!isStillCurrent(nodeId, graphId)) return
      codexSessionState.value = state
      if (options.onAfterSelect) await options.onAfterSelect(state)
    } catch (error) {
      options.onError?.(error)
    } finally {
      codexSessionLoading.value = false
    }
  }

  function codexMemoryClearTargetLabel(nodeId: string) {
    const safeNodeId = String(nodeId || '').trim()
    return codexSessionState.value?.supported
      ? `the current Codex Session memory for node "${safeNodeId}"`
      : `all memory for node "${safeNodeId}"`
  }

  return {
    codexSessionState,
    codexSessionLoading,
    refreshCodexSessions,
    chooseCodexSession,
    resetCodexSessions,
    codexMemoryClearTargetLabel,
  }
}
