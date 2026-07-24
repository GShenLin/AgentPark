import type { Ref } from 'vue'
import { getNodeInstanceConfig, listNodeInstanceConfigs, type NodeInstanceConfig, type NodeInstanceState } from '../../api'
import { clampBoardPosition, type BoardPosition } from './boardDragState'
import type { NodeCard, NodeRunState } from './context'
import {
  applyNodeConfigOutputToCard,
  applyNodeConfigToCard,
  createNodeCardFromConfig,
  nodeConfigRunDelta,
  nodeStateFromConfig,
  sanitizeBoardPoint,
} from './boardModel'
import { applyBoardRuntimeEvent } from './boardRuntimeEventProjection'

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
  type GraphRefreshState = {
    generation: number
    watermark: number
  }

  type InFlightGraphRefresh = {
    generation: number
    promise: Promise<void>
  }

  const graphRefreshStates = new Map<string, GraphRefreshState>()
  const allNodeRefreshPromises = new Map<string, InFlightGraphRefresh>()
  const singleNodeRefreshPromises = new Map<string, Promise<void>>()

  function currentGraphId() {
    return String(options.currentGraphId.value || 'default').trim() || 'default'
  }

  function graphRefreshState(graphId: string) {
    const existing = graphRefreshStates.get(graphId)
    if (existing) return existing
    const state = { generation: 0, watermark: 0 }
    graphRefreshStates.set(graphId, state)
    return state
  }

  function resetNodeConfigWatermark() {
    const state = graphRefreshState(currentGraphId())
    state.generation += 1
    state.watermark = 0
  }

  async function refreshNodeConfigsOnce(graphId: string, generation: number, watermark: number) {
    const response = await listNodeInstanceConfigs(graphId, watermark, 'board')
    const refreshState = graphRefreshState(graphId)
    if (currentGraphId() !== graphId || refreshState.generation !== generation) return

    const items = response.nodes || []
    const mismatchedConfig = items.find((cfg) => String(cfg.graph_id || '').trim() !== graphId)
    if (mismatchedConfig) {
      throw new Error(
        `Node config response for graph ${graphId} contained node ${String(mismatchedConfig.node_id || '').trim()} from graph ${String(mismatchedConfig.graph_id || '').trim() || '<missing>'}`,
      )
    }
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
      const serverPosition = clampBoardPosition({
        x: Number(uiCfg?.x ?? 0),
        y: Number(uiCfg?.y ?? 0),
      })
      const serverUi = sanitizeBoardPoint({
        x: serverPosition.x,
        y: serverPosition.y,
        width: uiCfg?.width,
        height: uiCfg?.height,
      })
      let ui = serverUi
      const draggingLocally = options.activeDragItemIds.has(nodeId)
      const pendingUi = options.pendingUiPositions.get(nodeId)
      const existingNode = options.nodes.value.find((n) => n.id === nodeId)
      if (draggingLocally) {
        const localPosition = options.getItemPosition(nodeId)
        const localUi = localPosition ? clampBoardPosition(localPosition) : null
        if (localUi) {
          ui = sanitizeBoardPoint({ ...serverUi, ...existingNode?.ui, ...localUi })
        }
      } else if (pendingUi) {
        if (pendingUi.x === serverPosition.x && pendingUi.y === serverPosition.y) {
          options.clearPendingUiPosition(nodeId, 'refresh_confirmed')
        } else {
          ui = sanitizeBoardPoint({ ...serverUi, ...existingNode?.ui, ...pendingUi })
        }
      }

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
    if (Number.isFinite(response.version || 0) && Number(response.version || 0) > refreshState.watermark) {
      refreshState.watermark = Number(response.version || 0)
    }
  }

  async function refreshNodeConfigs() {
    const graphId = currentGraphId()
    const refreshState = graphRefreshState(graphId)
    const existing = allNodeRefreshPromises.get(graphId)
    if (existing && existing.generation === refreshState.generation) {
      await existing.promise
      return
    }

    const generation = refreshState.generation
    const request = refreshNodeConfigsOnce(graphId, generation, refreshState.watermark)
    allNodeRefreshPromises.set(graphId, { generation, promise: request })
    try {
      await request
    } finally {
      if (allNodeRefreshPromises.get(graphId)?.promise === request) {
        allNodeRefreshPromises.delete(graphId)
      }
    }
  }

  async function refreshNodeConfig(nodeId: string, requestOptions: { signal?: AbortSignal } = {}) {
    const id = String(nodeId || '').trim()
    if (!id) return
    const graphId = currentGraphId()
    const generation = graphRefreshState(graphId).generation
    const requestKey = JSON.stringify([graphId, generation, id])
    const existingPromise = requestOptions.signal ? undefined : singleNodeRefreshPromises.get(requestKey)
    if (existingPromise) {
      await existingPromise
      return
    }

    const request = (async () => {
      const response = await getNodeInstanceConfig(id, graphId, requestOptions)
      if (currentGraphId() !== graphId || graphRefreshState(graphId).generation !== generation) return
      const previous = options.nodeConfigs.value[id]
      const responseConfig = response.node
      if (!responseConfig || String(responseConfig.node_id || '').trim() !== id) return
      if (String(responseConfig.graph_id || '').trim() !== graphId) {
        throw new Error(
          `Node config response for graph ${graphId} contained node ${id} from graph ${String(responseConfig.graph_id || '').trim() || '<missing>'}`,
        )
      }
      const cfg = { ...(previous || {}), ...responseConfig } as NodeInstanceConfig
      const previousVersion = Number((previous as any)?._config_version || 0)
      const nextVersion = Number((cfg as any)?._config_version || response.version || 0)
      if (previousVersion > 0 && nextVersion > 0 && nextVersion < previousVersion) return
      const nextConfigs = { ...options.nodeConfigs.value, [id]: cfg }
      const nextStates = { ...options.nodeStates.value, [id]: nodeStateFromConfig(cfg) }
      const node = options.nodes.value.find((item) => item.id === id)
      if (node) {
        const uiCfg = (cfg as any)?.ui
        const ui = sanitizeBoardPoint({
          x: Number(uiCfg?.x ?? node.ui.x ?? 0),
          y: Number(uiCfg?.y ?? node.ui.y ?? 0),
          width: uiCfg?.width ?? node.ui.width,
          height: uiCfg?.height ?? node.ui.height,
        })
        applyNodeConfigToCard(node, cfg, ui)
        const { out, runAtChanged, outputChanged } = nodeConfigRunDelta(previous, cfg)
        if (runAtChanged || outputChanged || !String(node.last_message || '').trim()) {
          applyNodeConfigOutputToCard(node, cfg, out)
          if (runAtChanged) options.triggerNodeDone(id)
        }
      }
      options.nodeConfigs.value = nextConfigs
      options.nodeStates.value = nextStates
      if (options.selectedNodeId.value === id) options.syncSelectedNodeWorkingPath(id)
    })()
    if (!requestOptions.signal) singleNodeRefreshPromises.set(requestKey, request)
    try {
      await request
    } finally {
      if (!requestOptions.signal && singleNodeRefreshPromises.get(requestKey) === request) {
        singleNodeRefreshPromises.delete(requestKey)
      }
    }
  }

  function applyNodeRuntimeEvent(payload: Record<string, unknown>) {
    const runtime = payload.node_runtime
    if (!runtime || typeof runtime !== 'object' || Array.isArray(runtime)) return
    const delta = runtime as Record<string, unknown>
    const nodeId = String(delta.node_id || payload.node_instance_id || payload.node_id || '').trim()
    if (!nodeId) return
    const previous = options.nodeConfigs.value[nodeId]
    if (!previous) return

    let next = { ...previous, ...delta } as NodeInstanceConfig
    next = applyBoardRuntimeEvent(next, payload)
    const eventName = String(payload.event || '').trim()
    const outputPreview = String(payload.output_preview || '').trim()
    if (outputPreview && ['node_message_done', 'node_output', 'node_error'].includes(eventName)) {
      next.last_message = outputPreview
    }
    options.nodeConfigs.value = { ...options.nodeConfigs.value, [nodeId]: next }
    options.nodeStates.value = { ...options.nodeStates.value, [nodeId]: nodeStateFromConfig(next) }

    const node = options.nodes.value.find((item) => item.id === nodeId)
    if (node) {
      applyNodeConfigToCard(node, next)
      if (outputPreview) applyNodeConfigOutputToCard(node, next, outputPreview)
    }
    if (eventName === 'node_message_done') options.triggerNodeDone(nodeId)
    if (options.selectedNodeId.value === nodeId) options.syncSelectedNodeWorkingPath(nodeId)
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
    applyNodeRuntimeEvent,
    hasActiveNodeWork,
    refreshNodeConfig,
    refreshNodeConfigs,
    refreshNodeConfigsAndMemory,
    resetNodeConfigWatermark,
  }
}
