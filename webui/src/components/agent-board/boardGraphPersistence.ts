import type { Ref } from 'vue'
import type { GraphConfig } from '../../api'
import type { LinkItem, NodeCard } from './context'
import { buildBoardGraphConfig } from './boardModel'

export function createBoardGraphPersistence(options: {
  graphSnapshot: Ref<GraphConfig | null>
  lastError: Ref<string | null>
  currentGraphId: Ref<string | null>
  currentGraphName: Ref<string | null>
  currentGraphWorkingPath: Ref<string>
  nodes: Ref<NodeCard[]>
  links: Ref<LinkItem[]>
  saveGraph: (graphId: string, config: GraphConfig, options?: { saveReason?: string; sourceGraphId?: string }) => Promise<unknown>
}) {
  let saveRunning = false
  let savePending = false
  let savePendingReason = 'unknown'

  function buildSnapshot(): GraphConfig {
    return buildBoardGraphConfig({
      graphId: options.currentGraphId.value || 'default',
      graphName: options.currentGraphName.value || 'default',
      workingPath: options.currentGraphWorkingPath.value,
      nodes: options.nodes.value,
      links: options.links.value,
    })
  }

  function syncSnapshot() {
    options.graphSnapshot.value = buildSnapshot()
  }

  async function persist(reason = 'unknown') {
    const saveReason = String(reason || '').trim() || 'unknown'
    if (saveRunning) {
      savePending = true
      savePendingReason = saveReason
      return
    }
    saveRunning = true
    savePending = false
    savePendingReason = 'unknown'
    try {
      const snapshot = buildSnapshot()
      const graphId = options.currentGraphId.value || snapshot.id || 'default'
      const payload: GraphConfig = {
        ...snapshot,
        id: graphId,
        name: options.currentGraphName.value || snapshot.name || graphId,
      }
      await options.saveGraph(graphId, payload, { saveReason })
      traceGraphSave({
        reason: saveReason,
        graphId,
        nodesCount: Array.isArray(snapshot.nodes) ? snapshot.nodes.length : 0,
        outputRoutesCount: snapshot.output_routes ? Object.keys(snapshot.output_routes).length : 0,
      })
    } catch (e: any) {
      options.lastError.value = String(e?.message || e)
    } finally {
      saveRunning = false
      if (savePending) {
        const pendingReason = savePendingReason
        savePendingReason = 'unknown'
        void persist(pendingReason)
      }
    }
  }

  return {
    buildSnapshot,
    syncSnapshot,
    persist,
  }
}

function traceGraphSave(payload: {
  reason: string
  graphId: string
  nodesCount: number
  outputRoutesCount: number
}) {
  if (typeof window === 'undefined') return
  const event = {
    ts: new Date().toISOString(),
    ...payload,
  }
  const bag = window as unknown as { __graphSaveTrace?: any[] }
  const trace = Array.isArray(bag.__graphSaveTrace) ? bag.__graphSaveTrace : []
  trace.push(event)
  if (trace.length > 200) trace.shift()
  bag.__graphSaveTrace = trace
  console.debug('[graph-save]', event)
}
