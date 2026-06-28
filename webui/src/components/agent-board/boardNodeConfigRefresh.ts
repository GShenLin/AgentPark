import type { Ref } from 'vue'
import { listNodeInstanceConfigs, type NodeInstanceConfig, type NodeInstanceState } from '../../api'
import { clampBoardPosition, type BoardPosition } from './boardDragState'
import type { NodeCard, NodeRunState } from './context'
import {
  applyNodeConfigOutputToCard,
  applyNodeConfigToCard,
  createNodeCardFromConfig,
  nodeConfigRunDelta,
  nodeStateFromConfig,
} from './boardModel'

export function createBoardNodeConfigRefresh(options: {
  currentGraphId: Ref<string | null>
  selectedNodeId: Ref<string | null>
  nodes: Ref<NodeCard[]>
  nodeConfigs: Ref<Record<string, NodeInstanceConfig>>
  nodeStates: Ref<Record<string, NodeInstanceState>>
  nodeRuns: Ref<Record<string, NodeRunState>>
  activeDragItemIds: Set<string>
  pendingUiPositions: Map<string, BoardPosition>
  getItemPosition: (itemId: string) => BoardPosition | null
  clearPendingUiPosition: (itemId: string, reason: string) => void
  triggerNodeDone: (nodeId: string) => void
  syncSelectedNodeWorkingPath: (nodeId: string) => void
  requestMemoryRefresh: () => void
}) {
  let nodeConfigWatermark = 0

  function resetNodeConfigWatermark() {
    nodeConfigWatermark = 0
  }

  async function refreshNodeConfigs() {
    const graphId = options.currentGraphId.value || 'default'
    const response = await listNodeInstanceConfigs(graphId, nodeConfigWatermark)
    const items = response.nodes || []
    const partial = !!response.partial
    const allNodeIds = Array.isArray(response.node_ids)
      ? new Set(response.node_ids.map((item) => String(item || '').trim()).filter(Boolean))
      : null
    const next: Record<string, NodeInstanceState> = partial ? { ...options.nodeStates.value } : {}
    const nextConfigs: Record<string, NodeInstanceConfig> = partial ? { ...options.nodeConfigs.value } : {}
    const prevConfigs = options.nodeConfigs.value

    if (allNodeIds) {
      for (const nodeId of Object.keys(nextConfigs)) {
        if (!allNodeIds.has(nodeId)) delete nextConfigs[nodeId]
      }
      for (const nodeId of Object.keys(next)) {
        if (!allNodeIds.has(nodeId)) delete next[nodeId]
      }
    }

    for (const cfg of items as NodeInstanceConfig[]) {
      const nodeId = String(cfg.node_id || '').trim()
      if (!nodeId) continue
      const uiCfg = (cfg as any)?.ui
      const serverUi = clampBoardPosition({
        x: Number(uiCfg?.x ?? 0),
        y: Number(uiCfg?.y ?? 0),
      })
      let ui = serverUi
      const draggingLocally = options.activeDragItemIds.has(nodeId)
      const pendingUi = options.pendingUiPositions.get(nodeId)
      if (draggingLocally) {
        const localPosition = options.getItemPosition(nodeId)
        const localUi = localPosition ? clampBoardPosition(localPosition) : null
        if (localUi) {
          ui = localUi
        }
      } else if (pendingUi) {
        if (pendingUi.x === serverUi.x && pendingUi.y === serverUi.y) {
          options.clearPendingUiPosition(nodeId, 'refresh_confirmed')
        } else {
          ui = pendingUi
        }
      }

      const existingNode = options.nodes.value.find((n) => n.id === nodeId)
      if (!existingNode) {
        options.nodes.value.push(createNodeCardFromConfig(cfg, ui))
      } else {
        applyNodeConfigToCard(existingNode, cfg, ui)
      }
    }

    const cfgIds = allNodeIds || new Set<string>(items.map((cfg) => String(cfg.node_id || '').trim()).filter(Boolean))
    if (allNodeIds || cfgIds.size > 0) {
      options.nodes.value = options.nodes.value.filter((n) => cfgIds.has(n.id))
    }

    for (const cfg of items as NodeInstanceConfig[]) {
      const nodeId = String(cfg.node_id || '')
      if (!nodeId) continue
      nextConfigs[nodeId] = cfg
      next[nodeId] = nodeStateFromConfig(cfg)

      const prev = (prevConfigs as any)?.[nodeId]
      const { out, runAtChanged, outputChanged } = nodeConfigRunDelta(prev, cfg)
      const changed = runAtChanged || outputChanged
      const node = options.nodes.value.find((n) => n.id === nodeId)
      if (node) {
        applyNodeConfigToCard(node, cfg)
      }
      const nodeNeedsHydrate = node ? !String(node.last_message || '').trim() : false
      const shouldUpdatePreview = changed || nodeNeedsHydrate
      if (shouldUpdatePreview && node) {
        applyNodeConfigOutputToCard(node, cfg, out)
        if (runAtChanged) options.triggerNodeDone(nodeId)
      }
    }
    options.nodeStates.value = next
    options.nodeConfigs.value = nextConfigs
    if (options.selectedNodeId.value) {
      options.syncSelectedNodeWorkingPath(options.selectedNodeId.value)
    }
    if (Number.isFinite(response.version || 0) && Number(response.version || 0) > nodeConfigWatermark) {
      nodeConfigWatermark = Number(response.version || 0)
    }
  }

  function hasActiveNodeWork() {
    if (Object.values(options.nodeRuns.value).some((run) => run.status === 'running' && !run.canceled)) return true
    return Object.values(options.nodeConfigs.value).some((cfg: any) => {
      const state = nodeStateFromConfig(cfg)
      if (state === 'working') return true
      if (Number(cfg?.pending_count ?? 0) > 0) return true
      return !!cfg?.inflight
    })
  }

  async function refreshNodeConfigsAndMemory() {
    await refreshNodeConfigs()
    options.requestMemoryRefresh()
  }

  return {
    hasActiveNodeWork,
    refreshNodeConfigs,
    refreshNodeConfigsAndMemory,
    resetNodeConfigWatermark,
  }
}
