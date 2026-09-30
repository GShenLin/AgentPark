import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { useMobileWorkspace } from './useMobileWorkspace'

type Workspace = ReturnType<typeof useMobileWorkspace>
const GRAPH_PARAM = 'mobile_graph'
const NODE_PARAM = 'mobile_node'

// The device is already identified by /board/:peerId. Keep only navigation IDs
// in the URL so remounts and browser reloads can fetch fresh device state.
export function useMobileBoardLocation(workspace: Workspace, enabled: boolean) {
  const restoring = ref(true)
  const initialized = ref(false)
  let disposed = false
  const selectionKey = () => JSON.stringify([
    workspace.view.value, workspace.selectedGraph.value?.id, workspace.selectedNode.value?.id,
  ])
  let savedSelection: string | undefined

  function saveLocation() {
    if (!enabled || restoring.value || disposed) return
    const selection = selectionKey()
    if (selection === savedSelection) return
    const url = new URL(window.location.href)
    const graphId = workspace.selectedGraph.value?.id
    const nodeId = workspace.selectedNode.value?.id
    if (!graphId || url.searchParams.get(GRAPH_PARAM) !== graphId || nodeId) url.searchParams.delete('mobile_group')
    if (graphId) url.searchParams.set(GRAPH_PARAM, graphId)
    else url.searchParams.delete(GRAPH_PARAM)
    if (graphId && nodeId) url.searchParams.set(NODE_PARAM, nodeId)
    else url.searchParams.delete(NODE_PARAM)
    if (url.href !== window.location.href) window.history.replaceState(window.history.state, '', url)
    savedSelection = selection
  }

  const stopWatching = watch(
    () => [workspace.view.value, workspace.selectedGraph.value?.id, workspace.selectedNode.value?.id],
    saveLocation,
  )
  onBeforeUnmount(() => {
    saveLocation()
    disposed = true
    stopWatching()
  })

  let initialization: Promise<void> | null = null
  function initialize() {
    if (!initialization) initialization = restoreSavedLocation().finally(() => { initialization = null })
    return initialization
  }

  async function restoreSavedLocation() {
    restoring.value = true
    const url = enabled ? new URL(window.location.href) : null
    const graphId = url?.searchParams.get(GRAPH_PARAM)
    const nodeId = url?.searchParams.get(NODE_PARAM)
    try {
      if (enabled) await workspace.restoreLocation('local', graphId || undefined, nodeId || undefined)
      else await workspace.loadPcs()
      if (disposed || workspace.error.value) return
      initialized.value = true
      workspace.activateConnection()
    } catch (cause) {
      if (!disposed) workspace.error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      // Drain selection watchers while writes are suspended. A failed restore
      // must retain the original destination for the next connection attempt.
      await nextTick()
      savedSelection = selectionKey()
      restoring.value = false
    }
  }

  return { initialize, restoring, initialized }
}
