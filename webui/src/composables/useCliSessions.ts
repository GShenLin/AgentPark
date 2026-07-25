import { ref } from 'vue'
import {
  listCliSessions,
  selectCliSession,
  type CliSessionListResponse,
} from '../api'

type CliSessionSelectionState = CliSessionListResponse & { ok?: boolean }

export function useCliSessions(options: {
  getNodeId: () => string
  getGraphId: () => string
  isEnabled?: () => boolean
  onAfterSelect?: (state: CliSessionSelectionState) => void | Promise<void>
  onError?: (error: unknown) => void
}) {
  const cliSessionState = ref<CliSessionListResponse | null>(null)
  const cliSessionLoading = ref(false)
  let cliSessionRequestGeneration = 0

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

  function resetCliSessions() {
    cliSessionRequestGeneration += 1
    cliSessionState.value = null
    cliSessionLoading.value = false
  }

  async function refreshCliSessions() {
    const { nodeId, graphId } = currentSelection()
    const generation = ++cliSessionRequestGeneration
    if (!nodeId || (options.isEnabled && !options.isEnabled())) {
      cliSessionState.value = null
      return
    }
    cliSessionLoading.value = true
    try {
      const state = await listCliSessions(nodeId, graphId)
      if (generation !== cliSessionRequestGeneration) return
      if (!isStillCurrent(nodeId, graphId)) return
      cliSessionState.value = state.supported ? state : null
    } catch {
      if (generation === cliSessionRequestGeneration) cliSessionState.value = null
    } finally {
      if (generation === cliSessionRequestGeneration) cliSessionLoading.value = false
    }
  }

  async function chooseCliSession(sessionId: string) {
    const { nodeId, graphId } = currentSelection()
    if (!nodeId || cliSessionLoading.value) return
    if (options.isEnabled && !options.isEnabled()) return
    cliSessionLoading.value = true
    try {
      const state = await selectCliSession(nodeId, sessionId, graphId)
      if (!isStillCurrent(nodeId, graphId)) return
      cliSessionState.value = state
      if (options.onAfterSelect) await options.onAfterSelect(state)
    } catch (error) {
      options.onError?.(error)
    } finally {
      cliSessionLoading.value = false
    }
  }

  function cliMemoryClearTargetLabel(nodeId: string) {
    const safeNodeId = String(nodeId || '').trim()
    return cliSessionState.value?.supported
      ? `the current ${cliSessionState.value.session_label} Session memory for node "${safeNodeId}"`
      : `all memory for node "${safeNodeId}"`
  }

  return {
    cliSessionState,
    cliSessionLoading,
    refreshCliSessions,
    chooseCliSession,
    resetCliSessions,
    cliMemoryClearTargetLabel,
  }
}
