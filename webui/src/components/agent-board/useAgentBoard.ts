import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  cloneNodeInstance,
  controlNodeInstance,
  createNodeInstance,
  deleteNodeInstance,
  emitGraph,
  getPasteAgentConfig,
  listNodeInstanceConfigs,
  listNodes,
  loadGraph,
  openNodeInstanceFolder,
  renameNodeInstance,
  saveGraph,
  setNodeInstanceState,
  startGraphRunner,
  stopNodeRun,
  updateNodeInstanceConfig,
  type GraphConfig,
  type MessageEnvelope,
  type NodeInstanceConfig,
  type NodeInstanceState,
  type NodeInfo,
  type PasteAgentConfig,
} from '../../api'
import { resolveDroppedPaths } from '../../composables/droppedPaths'
import { useGlobalState } from '../../composables/useGlobalState'
import {
  buildBoardPastePlan,
  hasBoardClipboardSnapshot,
  makeBoardCopySnapshot,
  type BoardClipboardSnapshot,
  type BoardPastePlan,
} from './boardClipboard'
import {
  clearPendingBoardPosition,
  rememberPendingBoardPositions,
  traceBoardDrag,
  type BoardPosition,
} from './boardDragState'
import {
  assignMissingNodePositions,
  canvasPointFromClient,
  computeBoardCanvasSize,
  nodeCardStyle,
} from './boardLayout'
import { boardLinkExists, createBoardLink, createBoardLinkSession, createBoardLinkTarget } from './boardLinks'
import { appendUniqueBoardAttachment, isBoardFileDropEvent } from './boardFiles'
import { createBoardGraphPersistence } from './boardGraphPersistence'
import { createBoardNodeConfigRefresh } from './boardNodeConfigRefresh'
import { removeBoardNodeRuntimeState, renameBoardNodeIdentity } from './boardNodeIdentity'
import { createBoardRuntimeRefresh } from './boardRuntimeRefresh'
import {
  getBoardNodeState,
  isBoardClockNode,
  isBoardClockRunning,
  isBoardNodeStopped,
  isBoardNodeWorking,
  resolveBoardNodeTypeId,
  waitForBoardNodeOutput,
} from './boardNodeRuntime'
import {
  computeNodeIdsInSelectionRect,
  selectionRectExceedsThreshold,
  selectionRectFromSession,
  type BoardSelectionSession,
} from './boardSelection'
import type { AgentBoardContext, DragSession, LinkItem, LinkSession, NodeCard, NodeRunState, PanSession } from './context'
import {
  clampX,
  applyNodeFieldPatchToCard,
  messageToText,
  mergeNodeConfigFields,
  buildLinkPath,
  getNodePortPosition,
  pruneLinksForNodePorts,
  normalizeGraphLinks,
  normalizePasteAgentConfig,
  normalizePortCount,
  normalizeSwitch,
  previewMessage,
  sanitizeBoardPoint,
  type BoardNodePlacement,
} from './boardModel'

export function useAgentBoard(): AgentBoardContext {
  const {
    selectedNodeId,
    lastError,
    memoryMode,
    memoryRefreshRequest,
    graphSnapshot,
    graphLoadRequest,
    currentGraphId,
    currentGraphName,
    currentGraphWorkingPath,
    nodeSettingsRequest,
    nodeEditorAttachments,
    nodeTriggerInputs,
  } =
    useGlobalState()

  const boardRef = ref<HTMLElement | null>(null)
  const canvasRef = ref<HTMLElement | null>(null)
  const canvasScale = ref(1)
  const selectionRect = ref<{ x: number; y: number; width: number; height: number } | null>(null)
  const suppressClickUntil = ref(0)

  const selectedItemIds = ref<string[]>([])
  let selectionSession: BoardSelectionSession | null = null

  let dragBatchStart: Record<string, { x: number; y: number }> | null = null
  let activeDragItemIds = new Set<string>()
  const pendingUiPositions = new Map<string, BoardPosition>()
  let nodeConfigRefreshPromise: Promise<void> | null = null
  let pasteCount = 0
  let clipboardSnapshot: BoardClipboardSnapshot | null = null
  let pasteAgentConfigCache: PasteAgentConfig | null = null

  function selectNode(id: string) {
    selectedNodeId.value = id
    selectedItemIds.value = [id]
    memoryMode.value = 'agent'
    syncSelectedNodeWorkingPath(id)
  }

  function openGraphPanel() {
    memoryMode.value = 'graph'
  }

  function openNodeSettings(id: string) {
    const targetId = String(id || '').trim()
    if (!targetId) return
    if (nodes.value.some((node) => node.id === targetId)) {
      selectNode(targetId)
      refreshNodeConfig(targetId).catch(() => null)
    } else {
      return
    }
    nodeSettingsRequest.value = {
      id: targetId,
      nonce: Date.now(),
    }
  }

  async function openNodeFolder(id: string) {
    const targetId = String(id || '').trim()
    if (!targetId) return
    if (!nodes.value.some((node) => node.id === targetId)) return
    selectNode(targetId)
    try {
      await openNodeInstanceFolder(targetId, currentGraphId.value || 'default')
    } catch (e: any) {
      lastError.value = `Failed to open node folder: ${String(e?.message || e)}`
    }
  }

  function openEmptyBoardPanel() {
    selectedNodeId.value = null
    selectedItemIds.value = []
    memoryMode.value = 'graph'
    selectedNodeWorkingPath.value = ''
    selectedNodeWorkingPathRevision.value += 1
  }

  function rememberPendingUiPositions(itemIds: Iterable<string>, reason: string) {
    rememberPendingBoardPositions({
      itemIds,
      pending: pendingUiPositions,
      reason,
      getPosition: getItemPosition,
    })
  }

  function clearPendingUiPosition(itemId: string, reason: string) {
    clearPendingBoardPosition({
      itemId,
      pending: pendingUiPositions,
      reason,
    })
  }

  function hasClipboardSnapshot() {
    return hasBoardClipboardSnapshot(clipboardSnapshot)
  }

  function buildPastePlanFromSnapshot(snapshot: BoardClipboardSnapshot) {
    pasteCount += 1
    const offset = 36 * pasteCount
    return buildBoardPastePlan({
      snapshot,
      offset,
      makeUniqueId,
      makeLinkId: () => `link-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    })
  }

  async function clonePastePlanNodes(snapshot: BoardClipboardSnapshot, plan: BoardPastePlan, targetGraphId: string) {
    const sourceGraphId = String(snapshot.graphId || 'default').trim() || 'default'
    const targetNodesById = new Map(plan.nodes.map((node) => [node.id, node]))
    for (const sourceNode of snapshot.nodes) {
      const targetId = plan.idMap.get(sourceNode.id)
      const targetNode = targetId ? targetNodesById.get(targetId) : null
      if (!targetNode) throw new Error(`Missing pasted node for ${sourceNode.id}`)
      await cloneNodeInstance(sourceNode.id, sourceGraphId, targetNode.id, targetNode.name, targetNode.ui, targetGraphId)
    }
  }

  async function applyPastePlanToBoard(plan: BoardPastePlan, persistReason: string) {
    nodes.value.push(...plan.nodes)
    links.value.push(...plan.links)

    selectedItemIds.value = plan.nodes.map((node) => node.id)
    if (selectedItemIds.value.length === 1) {
      const selectedId = selectedItemIds.value[0]
      if (selectedId && nodes.value.some((node) => node.id === selectedId)) {
        selectNode(selectedId)
      }
    }
    updateCanvasSize()
    syncGraphSnapshot()
    await persistGraphConfig(persistReason)
    refreshNodeConfigsAndMemory().catch(() => null)
  }

  async function ensurePasteAgentConfigLoaded(forceReload = false) {
    if (!forceReload && pasteAgentConfigCache) return pasteAgentConfigCache
    try {
      const cfg = await getPasteAgentConfig()
      pasteAgentConfigCache = normalizePasteAgentConfig(cfg)
      return pasteAgentConfigCache
    } catch (error) {
      pasteAgentConfigCache = null
      const message = error instanceof Error ? error.message : String(error || 'unknown error')
      throw new Error(message)
    }
  }

  async function pasteClipboardTextAsAgent(rawText: string) {
    const text = String(rawText || '').trim()
    if (!text) return false
    const pasteCfg = await ensurePasteAgentConfigLoaded(true)
    const providerId = String(pasteCfg.provider_id || '').trim()
    if (!providerId) {
      throw new Error('PasteAgent config provider_id is empty. Check /api/paste-agent/config and config/pastagent.json for the running backend.')
    }
    const nodeName = String(pasteCfg.name || pasteCfg.agent_id || 'PasteAgent').trim() || 'PasteAgent'
    const nodeId = await createNodeFromPalette('agent_node', nodeName, {
      provider_id: providerId,
      system_prompt: pasteCfg.system_prompt,
      mode: pasteCfg.mode,
      web_search: normalizeSwitch(pasteCfg.web_search, 'enabled'),
      thinking: normalizeSwitch(pasteCfg.thinking, 'enabled'),
      reasoning_effort: pasteCfg.reasoning_effort ?? 'high',
      tools: Array.isArray(pasteCfg.tools) ? pasteCfg.tools : [],
    })
    if (!nodeId) return false
    await sendNodeMessage(nodeId, text)
    return true
  }

  function nodeWorkingPath(nodeId: string) {
    const id = String(nodeId || '').trim()
    if (!id) return ''
    const cfg = (nodeConfigs.value as any)?.[id]
    const fromConfig = String(cfg?.working_path ?? '').trim()
    if (fromConfig) return fromConfig
    const node = nodes.value.find((item) => item.id === id)
    return String(node?.workingPath ?? '').trim()
  }

  function syncSelectedNodeWorkingPath(nodeId = selectedNodeId.value || '') {
    const path = nodeWorkingPath(String(nodeId || ''))
    selectedNodeWorkingPath.value = path
    selectedNodeWorkingPathRevision.value += 1
  }

  function isNodeSelected(id: string) {
    return selectedItemIds.value.includes(id)
  }

  function resolveNodePlacement(placement: BoardNodePlacement) {
    if (placement.kind === 'fixed') {
      return sanitizeBoardPoint(placement.ui)
    }

    const selectedPositions = selectedItemIds.value
      .map((id) => getItemPosition(id))
      .filter((p): p is { x: number; y: number } => !!p)
    const anchor = selectedPositions[0]
    return anchor
      ? { x: clampX(anchor.x + CARD_WIDTH + BOARD_GAP), y: Math.max(0, anchor.y) }
      : { x: BOARD_PADDING, y: BOARD_PADDING }
  }

  async function createNodeOnBoard(
    typeId: string,
    nodeName: string,
    fields: Record<string, unknown> | undefined,
    placement: BoardNodePlacement,
  ) {
    const safeTypeId = String(typeId || '').trim()
    if (!safeTypeId) return null
    const requestedId = String(nodeName || safeTypeId).trim() || safeTypeId
    const requestedNodeId = makeUniqueId(requestedId)
    const graphId = currentGraphId.value || 'default'
    const ui = resolveNodePlacement(placement)

    const created = await createNodeInstance(requestedNodeId, safeTypeId, requestedNodeId, graphId, ui)
    const nodeId = String(created?.node_id || requestedNodeId).trim() || requestedNodeId
    if (nodeId !== requestedNodeId && nodes.value.some((node) => node.id === nodeId)) {
      const message = `Node id collision after creation: ${nodeId}`
      lastError.value = message
      throw new Error(message)
    }
    if (fields && Object.keys(fields).length) {
      await updateNodeInstanceConfig(nodeId, { fields }, graphId)
    }

    const available = availableNodes.value.find((item) => item.id === safeTypeId)
    const inputNum = normalizePortCount((available as any)?.input_num, 1)
    const outputNum = normalizePortCount((available as any)?.output_num, 1)
    nodes.value.push({
      id: nodeId,
      typeId: safeTypeId,
      name: nodeId,
      inputNum,
      outputNum,
      ui,
      last_message: null,
      lastRuntimeEvent: null,
      runtimeEvents: [],
      providerId: String((fields as any)?.provider_id ?? '').trim(),
      mode: String((fields as any)?.mode ?? '').trim(),
      webSearch: normalizeSwitch((fields as any)?.web_search, 'disabled'),
      thinking: normalizeSwitch((fields as any)?.thinking, 'disabled'),
      reasoningEffort: (fields as any)?.reasoning_effort ?? 'high',
      systemPrompt: String((fields as any)?.system_prompt ?? ''),
      plugins: Array.isArray((fields as any)?.plugins) ? (fields as any).plugins.map(String).filter(Boolean) : [],
      tools: Array.isArray((fields as any)?.tools) ? (fields as any).tools.map(String).filter(Boolean) : [],
      mcpServers: Array.isArray((fields as any)?.mcp_servers) ? (fields as any).mcp_servers.map(String).filter(Boolean) : [],
      workingPath: String((fields as any)?.working_path ?? '').trim(),
    })
    selectedItemIds.value = [nodeId]
    selectedNodeId.value = nodeId
    memoryMode.value = 'agent'
    syncGraphSnapshot()
    await persistGraphConfig('create_node_from_palette')
    refreshNodeConfigsAndMemory().catch(() => null)
    ensureNodeConfig(nodeId).catch(() => null)
    scheduleActiveNodeRefresh()
    return nodeId
  }

  async function createNodeFromPalette(typeId: string, nodeName: string, fields?: Record<string, unknown>) {
    return createNodeOnBoard(typeId, nodeName, fields, { kind: 'selection-anchor' })
  }

  async function createNodeAtPosition(
    typeId: string,
    nodeName: string,
    ui: { x: number; y: number },
    fields?: Record<string, unknown>,
  ) {
    return createNodeOnBoard(typeId, nodeName, fields, { kind: 'fixed', ui })
  }

  function makeUniqueId(base: string, excludeId = '') {
    const raw = String(base || '').trim() || 'node'
    const cleaned = raw.replace(/[<>:"/\\|?*]/g, '_').trim() || 'node'
    const hasId = (id: string) => id !== excludeId && nodes.value.some((node) => node.id === id)

    if (!hasId(cleaned)) {
      return cleaned
    }
    for (let i = 1; i < 10000; i += 1) {
      const candidate = `${cleaned}${i}`
      if (!hasId(candidate)) {
        return candidate
      }
    }
    return `${cleaned}-${Date.now()}`
  }

  function applyLocalRename(oldId: string, newId: string) {
    renameBoardNodeIdentity({
      oldId,
      newId,
      nodes,
      links,
      selectedNodeId,
      selectedItemIds,
      nodeConfigs,
      nodeStates,
      nodeRuns,
      nodeDonePulse,
    })
  }

  async function renameNodeCard(itemId: string, nextName: string) {
    const trimmed = String(nextName || '').trim()
    if (!trimmed) return

    const exists = nodes.value.some((item) => item.id === itemId)
    if (!exists) return

    const finalId = makeUniqueId(trimmed, itemId)
    const graphId = currentGraphId.value || 'default'
    await renameNodeInstance(itemId, graphId, finalId, finalId)

    applyLocalRename(itemId, finalId)

    syncGraphSnapshot()
    await persistGraphConfig('rename_board_item')
    refreshNodeConfigsAndMemory().catch(() => null)
  }

  const CARD_WIDTH = 230
  const CARD_HEIGHT = 250
  const BOARD_PADDING = 40
  const BOARD_GAP = 70

  const availableNodes = ref<NodeInfo[]>([])
  const nodes = ref<NodeCard[]>([])
  const links = ref<LinkItem[]>([])
  const nodeConfigs = ref<Record<string, NodeInstanceConfig>>({})
  const linkSession = ref<LinkSession | null>(null)
  const dragSession = ref<DragSession>(null)
  const dragHoverTargetId = ref<string | null>(null)
  const panSession = ref<PanSession>(null)

  const canvasWidth = ref(1400)
  const canvasHeight = ref(900)

  const nodeRuns = ref<Record<string, NodeRunState>>({})
  const nodeStates = ref<Record<string, NodeInstanceState>>({})
  const nodeDonePulse = ref<Record<string, number>>({})
  const selectedNodeWorkingPath = ref('')
  const selectedNodeWorkingPathRevision = ref(0)
  const linkFlows = ref<{ id: string; linkId: string }[]>([])

  const LINK_FLOW_DURATION_MS = 1200
  const LINK_FLOW_BUBBLES = [0, 0.14, 0.28, 0.42, 0.56]
  const graphPersistence = createBoardGraphPersistence({
    graphSnapshot,
    lastError,
    currentGraphId,
    currentGraphName,
    currentGraphWorkingPath,
    nodes,
    links,
    saveGraph,
  })

  function appendNodeEditorAttachment(path: string, name = '') {
    appendUniqueBoardAttachment(nodeEditorAttachments.value, path, name)
  }

  function updateCanvasSize() {
    const size = computeBoardCanvasSize({
      nodes: nodes.value,
      cardWidth: CARD_WIDTH,
      cardHeight: CARD_HEIGHT,
      padding: BOARD_PADDING,
      emptyWidth: 1400,
      emptyHeight: 900,
      minWidth: 1000,
      minHeight: 700,
    })
    canvasWidth.value = size.width
    canvasHeight.value = size.height
  }

  function ensurePositions() {
    assignMissingNodePositions({
      nodes: nodes.value,
      cardWidth: CARD_WIDTH,
      cardHeight: CARD_HEIGHT,
      padding: BOARD_PADDING,
      gap: BOARD_GAP,
    })
    updateCanvasSize()
  }

  function syncGraphSnapshot() {
    graphPersistence.syncSnapshot()
  }

  async function persistGraphConfig(reason = 'unknown') {
    await graphPersistence.persist(reason)
  }

  async function refreshGraphLinks() {
    const graphId = currentGraphId.value || 'default'
    const config = await loadGraph(graphId)
    if ((currentGraphId.value || 'default') !== graphId) return
    if (!config || config.unchanged) return
    links.value = normalizeGraphLinks(config.output_routes || {})
    syncGraphSnapshot()
    if (graphSnapshot.value && Number(config.version || 0) > 0) {
      graphSnapshot.value = { ...graphSnapshot.value, version: Number(config.version || 0) }
    }
  }

  function applyGraphConfig(config: GraphConfig) {
    const graphId = currentGraphId.value || config.id || 'default'
    currentGraphWorkingPath.value = String((config as any)?.working_path || '').trim()
    activeDragItemIds.clear()
    pendingUiPositions.clear()
    selectedNodeId.value = null
    selectedNodeWorkingPath.value = ''
    selectedNodeWorkingPathRevision.value += 1
    nodes.value = []
    nodeConfigs.value = {}
    nodeStates.value = {}
    resetNodeConfigWatermark()

    void startGraphRunner(graphId).catch(() => null)

    links.value = normalizeGraphLinks(config.output_routes || {})

    updateCanvasSize()
    syncGraphSnapshot()
    if (graphSnapshot.value && Number(config.version || 0) > 0) {
      graphSnapshot.value = { ...graphSnapshot.value, version: Number(config.version || 0) }
    }
  }

  function detachLinks(id: string) {
    const before = links.value.length
    links.value = links.value.filter((link) => !(link.from.node === id || link.to.node === id))
    if (links.value.length !== before) {
      syncGraphSnapshot()
      void persistGraphConfig('detach_links')
    }
  }

  async function deleteNodeCard(nodeId: string) {
    const index = nodes.value.findIndex((node) => node.id === nodeId)
    if (index === -1) return
    lastError.value = null
    const graphId = currentGraphId.value || 'default'
    try {
      await deleteNodeInstance(nodeId, graphId)
    } catch (e: any) {
      lastError.value = String(e?.message || e)
      await refreshNodeConfigsAndMemory().catch(() => null)
      throw e
    }
    detachLinks(nodeId)
    const confirmedIndex = nodes.value.findIndex((node) => node.id === nodeId)
    if (confirmedIndex !== -1) {
      nodes.value.splice(confirmedIndex, 1)
    }
    selectedItemIds.value = selectedItemIds.value.filter((id) => id !== nodeId)
    if (selectedNodeId.value === nodeId) {
      selectedNodeId.value = null
    }

    removeBoardNodeRuntimeState({
      nodeId,
      nodeStates,
      nodeDonePulse,
      nodeRuns,
    })

    syncGraphSnapshot()
    void persistGraphConfig('delete_node_card')
  }

  function isDragging(id: string) {
    return dragSession.value?.itemId === id
  }

  function itemStyle(id: string) {
    return nodeCardStyle({
      node: nodes.value.find((n) => n.id === id),
      dragging: isDragging(id),
    })
  }

  function onItemClick(id: string, event: MouseEvent) {
    if (Date.now() < suppressClickUntil.value) return
    if (event.altKey) {
      detachLinks(id)
      return
    }

    if (event.ctrlKey) {
      const selected = new Set<string>(selectedItemIds.value)
      if (selected.has(id)) selected.delete(id)
      else selected.add(id)
      selectedItemIds.value = Array.from(selected)
      if (!selectedItemIds.value.length) {
        selectedNodeId.value = null
      }
      return
    }

    if (nodes.value.some((n) => n.id === id)) {
      selectedItemIds.value = [id]
      selectNode(id)
      refreshNodeConfig(id).catch(() => null)
    }
  }

  function onItemPointerDown(id: string, event: PointerEvent) {
    if (event.button !== 0) return
    const target = event.target as HTMLElement | null
    if (target?.closest('button, input, textarea, select, a')) return

    dragHoverTargetId.value = null
    const selected = new Set<string>(selectedItemIds.value)
    if (!selected.has(id) && !event.ctrlKey && !event.metaKey) {
      if (nodes.value.some((n) => n.id === id)) {
        selectNode(id)
      }
    }
    activeDragItemIds = new Set(selectedItemIds.value)
    dragBatchStart = {}
    for (const itemId of selectedItemIds.value) {
      const pos = getItemPosition(itemId)
      if (!pos) continue
      dragBatchStart[itemId] = { x: pos.x, y: pos.y }
    }

    const node = nodes.value.find((n) => n.id === id)
    if (!node) return
    let startX = node.ui.x
    let startY = node.ui.y
    dragSession.value = {
      itemId: id,
      pointerId: event.pointerId,
      startPointerX: event.clientX,
      startPointerY: event.clientY,
      startX,
      startY,
      moved: false,
    }
    traceBoardDrag('drag_start', {
      itemId: id,
      pointerId: event.pointerId,
      selectedIds: [...selectedItemIds.value],
      startX,
      startY,
    })
    ;(event.currentTarget as HTMLElement | null)?.setPointerCapture(event.pointerId)
  }

  function onItemPointerMove(event: PointerEvent) {
    const session = dragSession.value
    if (!session) return
    if (event.pointerId !== session.pointerId) return
    const dx = event.clientX - session.startPointerX
    const dy = event.clientY - session.startPointerY
    if (!session.moved && Math.hypot(dx, dy) > 4) session.moved = true

    const movingIds = selectedItemIds.value.length ? selectedItemIds.value : [session.itemId]
    for (const itemId of movingIds) {
      const startPos = dragBatchStart?.[itemId]
      if (!startPos) continue
      const node = nodes.value.find((n) => n.id === itemId)
      if (!node) continue
      node.ui.x = clampX(startPos.x + dx)
      node.ui.y = Math.max(0, startPos.y + dy)
    }
    updateCanvasSize()
    const payload = getLastItemPayload(session.itemId)
    if (!session.moved || !payload) {
      dragHoverTargetId.value = null
    } else {
      dragHoverTargetId.value = getDropTargetItemId(event.clientX, event.clientY, new Set(movingIds))
    }
    event.preventDefault()
  }

  async function waitForNodeOutput(
    nodeId: string,
    prevRunAt: string | null,
    prevMessage: string | null,
    graphId: string,
  ): Promise<{ status: 'completed' | 'stopped' | 'deadline'; message: string }> {
    return waitForBoardNodeOutput({
      nodeId,
      prevRunAt,
      prevMessage,
      graphId,
      listNodeInstanceConfigs,
    })
  }

  function triggerNodeDone(nodeId: string) {
    nodeDonePulse.value = { ...nodeDonePulse.value, [nodeId]: Date.now() }
  }

  function getNodeState(nodeId: string): NodeInstanceState {
    return getBoardNodeState(nodeStates.value, nodeId)
  }

  function isNodeWorking(nodeId: string) {
    return isBoardNodeWorking(nodeStates.value, nodeId)
  }

  function isClockNode(nodeId: string) {
    return isBoardClockNode({
      nodeConfigs: nodeConfigs.value,
      nodes: nodes.value,
      nodeId,
    })
  }

  function isClockRunning(nodeId: string) {
    return isBoardClockRunning({
      nodeConfigs: nodeConfigs.value,
      nodes: nodes.value,
      nodeId,
    })
  }

  function isNodeStopped(nodeId: string) {
    return isBoardNodeStopped(nodeStates.value, nodeId)
  }

  function isNodeRunning(nodeId: string) {
    const id = String(nodeId || '').trim()
    if (!id) return false
    const activeRun = Object.values(nodeRuns.value).some(
      (run) => run.nodeId === id && run.status === 'running' && !run.canceled,
    )
    if (activeRun) return true
    const state = getNodeState(id)
    if (state === 'stop') return false
    const cfg = nodeConfigs.value[id] as any
    const pendingCount = Number(cfg?.pending_count ?? 0)
    return state === 'working' || pendingCount > 0 || !!cfg?.inflight
  }

  function markNodeStopRequested(nodeId: string) {
    const id = String(nodeId || '').trim()
    if (!id) return
    const cfg = nodeConfigs.value[id]
    nodeConfigs.value = {
      ...nodeConfigs.value,
      [id]: {
        ...(cfg || ({ node_id: id, type_id: '' } as NodeInstanceConfig)),
        node_id: id,
        _stop_requested: true,
        state: 'working',
        last_message: 'Stop requested. Cancelling active work.',
      } as NodeInstanceConfig,
    }
    nodeStates.value = { ...nodeStates.value, [id]: 'working' }
    const node = nodes.value.find((item) => item.id === id)
    if (node) {
      node.last_message = 'Stop requested. Cancelling active work.'
    }
  }

  async function stopNodeWork(nodeId: string) {
    const id = String(nodeId || '').trim()
    if (!id) return
    await stopNodeWorkNow(id)
  }

  async function stopNodeWorkNow(nodeId: string) {
    const graphId = currentGraphId.value || 'default'
    if (!isClockNode(nodeId)) {
      markNodeStopRequested(nodeId)
    }
    const activeRuns = Object.values(nodeRuns.value).filter(
      (run) => run.nodeId === nodeId && run.status === 'running' && !run.canceled,
    )
    try {
      if (activeRuns.length) {
        const nextRuns = { ...nodeRuns.value }
        for (const run of activeRuns) {
          nextRuns[run.runId] = { ...run, canceled: true, status: 'stopped' }
        }
        nodeRuns.value = nextRuns
        await Promise.allSettled(activeRuns.map((run) => stopNodeRun(run.runId)))
      }

      if (isClockNode(nodeId)) {
        await toggleNodeStop(nodeId)
        return
      }

      const res = await controlNodeInstance(nodeId, 'stop', graphId)
      nodeStates.value = { ...nodeStates.value, [nodeId]: res.state }
      await refreshNodeConfigsAndMemory().catch(() => null)
    } catch (e: any) {
      lastError.value = String(e?.message || e)
      await refreshNodeConfigsAndMemory().catch(() => null)
      throw e
    }
  }

  async function startClockNode(nodeId: string) {
    if (!isClockNode(nodeId)) return
    const graphId = currentGraphId.value || 'default'
    const res = await controlNodeInstance(nodeId, 'start', graphId)
    nodeStates.value = { ...nodeStates.value, [nodeId]: res.state }
    await startGraphRunner(graphId).catch(() => null)
    await refreshNodeConfigsAndMemory().catch(() => null)
    scheduleActiveNodeRefresh()
  }

  async function toggleNodeStop(nodeId: string) {
    const graphId = currentGraphId.value || 'default'
    if (isClockNode(nodeId)) {
      const action = getNodeState(nodeId) === 'stop' ? 'start' : 'stop'
      const res = await controlNodeInstance(nodeId, action, graphId)
      nodeStates.value = { ...nodeStates.value, [nodeId]: res.state }
      if (res.state === 'working') {
        await startGraphRunner(graphId).catch(() => null)
        scheduleActiveNodeRefresh()
      }
      await refreshNodeConfigsAndMemory().catch(() => null)
      return
    }
    const current = getNodeState(nodeId)
    const next: NodeInstanceState = current === 'stop' ? 'idle' : 'stop'
    await setNodeInstanceState(nodeId, next, graphId)
    nodeStates.value = { ...nodeStates.value, [nodeId]: next }
    if (next === 'idle') {
      startGraphRunner(graphId).catch(() => null)
      scheduleActiveNodeRefresh()
    }
  }

  function requestMemoryRefresh() {
    memoryRefreshRequest.value += 1
  }

  function requestSelectedNodeMemoryRefresh(nodeId: string) {
    if (selectedNodeId.value !== nodeId) return
    if (memoryMode.value !== 'agent') return
    requestMemoryRefresh()
  }

  const nodeConfigRefresh = createBoardNodeConfigRefresh({
    currentGraphId,
    selectedNodeId,
    nodes,
    nodeConfigs,
    nodeStates,
    nodeRuns,
    activeDragItemIds,
    pendingUiPositions,
    getItemPosition,
    clearPendingUiPosition,
    triggerNodeDone,
    syncSelectedNodeWorkingPath,
    requestMemoryRefresh,
  })
  const {
    hasActiveNodeWork,
    refreshNodeConfigs,
    refreshNodeConfigsAndMemory,
    resetNodeConfigWatermark,
  } = nodeConfigRefresh

  const runtimeRefresh = createBoardRuntimeRefresh({
    currentGraphId,
    refreshNodeConfigs,
    refreshGraphLinks,
    hasActiveNodeWork,
  })
  const {
    scheduleActiveNodeRefresh,
    startGraphEventStream,
    stopActiveNodeRefresh,
    stopGraphEventStream,
  } = runtimeRefresh

  async function ensureNodeConfig(nodeId: string) {
    const graphId = currentGraphId.value || 'default'
    if (nodeConfigs.value[nodeId]) return
    const node = nodes.value.find((n) => n.id === nodeId)
    if (!node) return
    await createNodeInstance(node.id, node.typeId, node.name, graphId, node.ui).catch(() => null)
    await refreshNodeConfigsAndMemory().catch(() => null)
  }

  async function refreshNodeConfig(nodeId: string) {
    const id = String(nodeId || '').trim()
    if (!id) return
    if (!nodes.value.some((node) => node.id === id)) return
    if (!nodeConfigs.value[id]) {
      await ensureNodeConfig(id)
      return
    }
    if (!nodeConfigRefreshPromise) {
      nodeConfigRefreshPromise = refreshNodeConfigs().finally(() => {
        nodeConfigRefreshPromise = null
      })
    }
    await nodeConfigRefreshPromise
  }

  async function triggerNode(nodeId: string) {
    const id = String(nodeId || '').trim()
    if (!id) return
    const node = nodes.value.find((n) => n.id === id)
    if (!node) return

    const graphId = currentGraphId.value || 'default'
    const cfg = (nodeConfigs.value as any)?.[id] || null
    const input = String(nodeTriggerInputs.value[id] || '')
    const prevRunAt = String(cfg?.last_run_at ?? '')
    const prevMessage = String(cfg?.last_message ?? '')
    await startGraphRunner(graphId).catch(() => null)
    await emitGraph(graphId, id, input).catch(() => null)
    scheduleActiveNodeRefresh()
    const waited = await waitForNodeOutput(id, prevRunAt || null, prevMessage || null, graphId)
    if (waited.status === 'completed') {
      node.last_message = waited.message
    }
    await refreshNodeConfigsAndMemory().catch(() => null)
  }

  async function sendNodeMessage(nodeId: string, message: string | MessageEnvelope) {
    const id = String(nodeId || '').trim()
    if (!id) return

    const text = messageToText(message)
    const graphId = currentGraphId.value || 'default'
    const typeId = resolveBoardNodeTypeId({
      nodeConfigs: nodeConfigs.value,
      nodes: nodes.value,
      nodeId: id,
    })
    if (!typeId) return
    if (getNodeState(id) === 'stop') {
      const resumed = await setNodeInstanceState(id, 'idle', graphId)
      nodeStates.value = { ...nodeStates.value, [id]: resumed.state }
    }

    if (typeId === 'basic_trigger_node') {
      if (text) {
        const node = nodes.value.find((n) => n.id === id)
        if (node) node.last_message = text
        await setNodeFields(id, { OutputText: text })
      }
      await triggerNode(id)
      return
    }

    if (!text && typeof message === 'string') return
    lastError.value = null
    try {
      const node = nodes.value.find((n) => n.id === id)
      if (node) node.last_message = text
      requestSelectedNodeMemoryRefresh(id)
      await startGraphRunner(graphId).catch(() => null)
      await emitGraph(graphId, id, message)
      await refreshNodeConfigsAndMemory().catch(() => null)
      scheduleActiveNodeRefresh()
    } catch (e: any) {
      lastError.value = String(e?.message || e)
      throw e
    }
  }

  async function setNodeFields(nodeId: string, fields: Record<string, unknown>) {
    const graphId = currentGraphId.value || 'default'
    lastError.value = null
    const result = await updateNodeInstanceConfig(nodeId, { fields }, graphId)
    const existing = nodeConfigs.value[nodeId]
    const fallbackNode = nodes.value.find((n) => n.id === nodeId)
    const merged = mergeNodeConfigFields({
      nodeId,
      graphId,
      existing,
      fallbackTypeId: fallbackNode?.typeId || '',
      fallbackName: fallbackNode?.name || '',
      fields,
    })
    nodeConfigs.value = { ...nodeConfigs.value, [nodeId]: merged }

    const node = nodes.value.find((item) => item.id === nodeId)
    if (node) {
      applyNodeFieldPatchToCard(node, merged, fields)
    }

    if (selectedNodeId.value === nodeId) {
      syncSelectedNodeWorkingPath(nodeId)
    }

    await refreshNodeConfigsAndMemory().catch(() => null)
    pruneInvalidLinksForNode(nodeId)
    syncGraphSnapshot()
    await persistGraphConfig('set_node_fields')
    return result
  }

  async function clearNodeFields(nodeId: string, fields: string[]) {
    const graphId = currentGraphId.value || 'default'
    const clearFields = Array.from(new Set((fields || []).map((item) => String(item || '').trim()).filter(Boolean)))
    if (!nodeId || clearFields.length === 0) return
    lastError.value = null
    const result = await updateNodeInstanceConfig(nodeId, { clear_fields: clearFields }, graphId)
    const existing = nodeConfigs.value[nodeId]
    if (existing) {
      const next = { ...existing }
      for (const field of clearFields) {
        delete (next as any)[field]
      }
      nodeConfigs.value = { ...nodeConfigs.value, [nodeId]: next }
    }
    await refreshNodeConfigsAndMemory().catch(() => null)
    syncGraphSnapshot()
    await persistGraphConfig('clear_node_fields')
    return result
  }

  function getDropTargetItemId(clientX: number, clientY: number, excludeIds: Set<string>) {
    const stack = typeof document.elementsFromPoint === 'function' ? document.elementsFromPoint(clientX, clientY) : []
    for (const el of stack) {
      const host = (el as HTMLElement | null)?.closest?.('[data-board-item-id]') as HTMLElement | null
      if (!host) continue
      const id = String(host.getAttribute('data-board-item-id') || '').trim()
      if (id && !excludeIds.has(id)) return id
    }
    return null
  }

  function getLastItemPayload(itemId: string) {
    const cfg = (nodeConfigs.value as any)?.[itemId]
    const inflightPayload = (cfg as any)?.inflight?.payload
    const inflightText = messageToText(inflightPayload as MessageEnvelope)
    if (inflightText) return inflightText
    const pendingList = Array.isArray((cfg as any)?.pending) ? ((cfg as any).pending as any[]) : []
    if (pendingList.length > 0) {
      const lastPendingPayload = pendingList[pendingList.length - 1]?.payload
      const pendingText = messageToText(lastPendingPayload as MessageEnvelope)
      if (pendingText) return pendingText
    }
    const node = nodes.value.find((n) => n.id === itemId)
    if (node?.last_message && String(node.last_message).trim()) return String(node.last_message)
    if (cfg?.last_message != null && String(cfg.last_message).trim()) return String(cfg.last_message)
    return null
  }

  function restoreDraggedPreviewPositions(itemIds: string[]) {
    for (const itemId of itemIds) {
      const startPos = dragBatchStart?.[itemId]
      if (!startPos) continue
      const node = nodes.value.find((n) => n.id === itemId)
      if (!node) continue
      node.ui.x = startPos.x
      node.ui.y = startPos.y
    }
  }

  function endDrag(event: PointerEvent) {
    const session = dragSession.value
    if (!session) return

    const movingIds = selectedItemIds.value.length ? [...selectedItemIds.value] : [session.itemId]
    const targetId = getDropTargetItemId(event.clientX, event.clientY, new Set(movingIds))
    const payload = getLastItemPayload(session.itemId)
    const wasMoved = session.moved
    dragSession.value = null
    dragHoverTargetId.value = null
    activeDragItemIds.clear()
    if (!wasMoved) {
      dragBatchStart = null
      traceBoardDrag('drag_end', {
        itemId: session.itemId,
        pointerId: session.pointerId,
        moved: false,
        targetId,
      })
      return
    }
    suppressClickUntil.value = Date.now() + 250
    traceBoardDrag('drag_end', {
      itemId: session.itemId,
      pointerId: session.pointerId,
      moved: true,
      targetId,
      movingIds,
      sentByDrop: !!(targetId && payload),
    })

    if (targetId && payload) {
      restoreDraggedPreviewPositions(movingIds)
      updateCanvasSize()
      syncGraphSnapshot()
      lastError.value = null
      if (nodes.value.some((n) => n.id === targetId)) selectNode(targetId)
      sendNodeMessage(targetId, payload).catch((e: any) => {
        lastError.value = String(e?.message || e)
      })
      dragBatchStart = null
      event.preventDefault()
      return
    }

    updateCanvasSize()
    syncGraphSnapshot()
    rememberPendingUiPositions(movingIds, 'end_drag')
    void persistDraggedItemPositions(movingIds).catch((e: any) => {
      lastError.value = String(e?.message || e)
    })
    void persistGraphConfig('end_drag')
    dragBatchStart = null
    event.preventDefault()
  }

  async function persistDraggedItemPositions(itemIds?: Iterable<string>) {
    const graphId = currentGraphId.value || 'default'
    const tasks: Array<{ itemId: string; ui: { x: number; y: number }; request: Promise<{ ok: boolean }> }> = []
    const include = itemIds ? new Set(itemIds) : null

    for (const node of nodes.value) {
      if (!node?.ui) continue
      if (include && !include.has(node.id)) continue
      const ui = { x: clampX(node.ui.x), y: Math.max(0, node.ui.y) }
      tasks.push({
        itemId: node.id,
        ui,
        request: updateNodeInstanceConfig(node.id, { ui }, graphId),
      })
    }

    if (!tasks.length) return
    traceBoardDrag('persist_drag_start', {
      graphId,
      itemIds: tasks.map((task) => task.itemId),
    })
    const results = await Promise.allSettled(tasks.map((task) => task.request))
    const failures: string[] = []
    for (const [index, result] of results.entries()) {
      const task = tasks[index]
      if (!task) continue
      if (result.status === 'fulfilled') {
        traceBoardDrag('persist_drag_sent', {
          itemId: task.itemId,
          x: task.ui.x,
          y: task.ui.y,
        })
        continue
      }
      clearPendingUiPosition(task.itemId, 'persist_failed')
      failures.push(`${task.itemId}: ${String(result.reason instanceof Error ? result.reason.message : result.reason)}`)
    }
    if (failures.length) {
      throw new Error(`Failed to persist dragged item positions (${failures.join('; ')})`)
    }
  }

  function onPanMouseMove(event: MouseEvent) {
    const session = panSession.value
    if (!session) return
    const board = boardRef.value
    if (!board) return

    const dx = event.clientX - session.startPointerX
    const dy = event.clientY - session.startPointerY
    board.scrollLeft = session.startScrollLeft - dx
    board.scrollTop = session.startScrollTop - dy
    event.preventDefault()
  }

  function onPanEnd(event: Event) {
    if (!panSession.value) return
    panSession.value = null
    window.removeEventListener('mousemove', onPanMouseMove)
    window.removeEventListener('mouseup', onPanEnd)
    window.removeEventListener('blur', onPanEnd)
    suppressClickUntil.value = Date.now() + 250
    if (event.cancelable) event.preventDefault()
  }

  function onBoardMouseDownCapture(event: MouseEvent) {
    if (event.button === 0) {
      const target = event.target as HTMLElement | null
      const overItem = !!target?.closest('.node-card, .node-side-editor, .node-output-routes-panel, .modal, .context-menu')
      if (!overItem) {
        if (!(event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)) {
          openEmptyBoardPanel()
        }
        if (!event.ctrlKey) {
          selectedItemIds.value = []
          selectedNodeId.value = null
        }
        const pt = getCanvasPoint(event as unknown as PointerEvent)
        selectionSession = {
          startX: pt.x,
          startY: pt.y,
          currentX: pt.x,
          currentY: pt.y,
          additive: !!event.ctrlKey,
        }
        updateSelectionRect()
        window.addEventListener('pointermove', onSelectionPointerMove)
        window.addEventListener('pointerup', onSelectionPointerUp)
        window.addEventListener('blur', onSelectionPointerUp)
      }
    }

    if (event.button === 2) {
      const target = event.target as HTMLElement | null
      const overItem = !!target?.closest('.node-card, .node-side-editor, .node-output-routes-panel, .modal, .context-menu')
      if (!overItem) {
        event.preventDefault()
      }
    }

    if (event.button !== 1) return
    const board = boardRef.value
    if (!board) return

    panSession.value = {
      startPointerX: event.clientX,
      startPointerY: event.clientY,
      startScrollLeft: board.scrollLeft,
      startScrollTop: board.scrollTop,
    }
    window.addEventListener('mousemove', onPanMouseMove)
    window.addEventListener('mouseup', onPanEnd)
    window.addEventListener('blur', onPanEnd)
    event.preventDefault()
  }

  function onNodePaletteDragStart(_node: NodeInfo, event: DragEvent) {
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'none'
    }
  }

  function onBoardDragOver(event: DragEvent) {
    event.preventDefault()
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'copy'
    }
    if (isBoardFileDropEvent(event)) {
      dragHoverTargetId.value = null
    }
  }

  function onNodeCardDragOver(id: string, event: DragEvent) {
    if (!isBoardFileDropEvent(event)) return
    event.preventDefault()
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'copy'
    }
    dragHoverTargetId.value = String(id || '').trim() || null
  }

  async function onNodeCardDrop(nodeId: string, event: DragEvent) {
    const id = String(nodeId || '').trim()
    dragHoverTargetId.value = null
    if (!id || !isBoardFileDropEvent(event)) return

    event.preventDefault()
    lastError.value = null
    try {
      const droppedItems = await resolveDroppedPaths(event, `board-node-drop-${id}-${Date.now()}`)
      if (!droppedItems.length) return
      for (const item of droppedItems) {
        appendNodeEditorAttachment(item.path, item.name)
      }
      if (nodes.value.some((node) => node.id === id)) {
        selectNode(id)
        refreshNodeConfig(id).catch(() => null)
      }
    } catch (e: any) {
      lastError.value = String(e?.message || e)
    }
  }

  function getCanvasPoint(event: PointerEvent | DragEvent) {
    return canvasPointFromClient({
      canvas: canvasRef.value,
      clientX: event.clientX,
      clientY: event.clientY,
      scale: canvasScale.value,
    })
  }

  function getItemPosition(id: string) {
    const node = nodes.value.find((n) => n.id === id)
    if (node?.ui) return { x: node.ui.x, y: node.ui.y }
    return null
  }

  function updateSelectionRect() {
    selectionRect.value = selectionRectFromSession(selectionSession)
  }

  function computeItemsInRect(rect: { x: number; y: number; width: number; height: number }) {
    return computeNodeIdsInSelectionRect({
      nodes: nodes.value,
      rect,
      cardWidth: CARD_WIDTH,
      cardHeight: CARD_HEIGHT,
    })
  }

  function onSelectionPointerMove(event: PointerEvent) {
    if (!selectionSession) return
    const { x, y } = getCanvasPoint(event)
    selectionSession.currentX = x
    selectionSession.currentY = y
    updateSelectionRect()
  }

  function clearSelectionSession() {
    selectionSession = null
    selectionRect.value = null
    window.removeEventListener('pointermove', onSelectionPointerMove)
    window.removeEventListener('pointerup', onSelectionPointerUp)
    window.removeEventListener('blur', onSelectionPointerUp)
  }

  function onSelectionPointerUp() {
    const rect = selectionRect.value
    const session = selectionSession
    if (rect && session && selectionRectExceedsThreshold(rect)) {
      const selected = computeItemsInRect(rect)
      const merged = new Set<string>(session.additive ? selectedItemIds.value : [])
      for (const id of selected) merged.add(id)
      selectedItemIds.value = Array.from(merged)
      if (selectedItemIds.value.length === 1) {
        const id = selectedItemIds.value[0]
        if (id) {
          if (nodes.value.some((n) => n.id === id)) selectNode(id)
        }
      }
    }
    clearSelectionSession()
  }

  function makeCopySnapshot() {
    return makeBoardCopySnapshot({
      graphId: currentGraphId.value || 'default',
      nodes: nodes.value,
      links: links.value,
      selectedItemIds: selectedItemIds.value,
    })
  }

  async function pasteSnapshot() {
    if (!hasClipboardSnapshot() || !clipboardSnapshot) return
    const targetGraphId = currentGraphId.value || 'default'
    const plan = buildPastePlanFromSnapshot(clipboardSnapshot)
    await clonePastePlanNodes(clipboardSnapshot, plan, targetGraphId)
    await applyPastePlanToBoard(plan, 'paste_snapshot')
  }

  function onWindowKeyDown(event: KeyboardEvent) {
    const target = event.target as HTMLElement | null
    if (target?.closest('input, textarea, [contenteditable="true"], select')) return
    if (!(event.ctrlKey || event.metaKey)) return
    const key = event.key.toLowerCase()
    if (key === 'c') {
      const selection = window.getSelection()
      const hasSelectedText = !!selection && !selection.isCollapsed && String(selection.toString() || '').trim().length > 0
      if (hasSelectedText) return
      const snapshot = makeCopySnapshot()
      if (!snapshot) {
        clipboardSnapshot = null
        pasteCount = 0
        return
      }
      clipboardSnapshot = snapshot
      event.preventDefault()
      return
    }
  }

  function onWindowPaste(event: ClipboardEvent) {
    const target = event.target as HTMLElement | null
    if (target?.closest('input, textarea, [contenteditable="true"], select')) return

    const text = String(event.clipboardData?.getData('text/plain') || '')
    if (hasClipboardSnapshot()) {
      event.preventDefault()
      lastError.value = null
      pasteSnapshot().catch((e: any) => {
        lastError.value = String(e?.message || e)
      })
      return
    }

    if (!text.trim()) return
    event.preventDefault()
    lastError.value = null
    pasteClipboardTextAsAgent(text).catch((e: any) => {
      lastError.value = String(e?.message || e)
    })
  }

  function onBoardWheel(event: WheelEvent) {
    if (!event.ctrlKey) return
    const board = boardRef.value
    const canvas = canvasRef.value
    if (!board || !canvas) return

    event.preventDefault()
    const rect = canvas.getBoundingClientRect()
    const pointerX = event.clientX - rect.left
    const pointerY = event.clientY - rect.top
    const worldX = pointerX / (canvasScale.value || 1)
    const worldY = pointerY / (canvasScale.value || 1)

    const factor = event.deltaY < 0 ? 1.1 : 0.9
    const nextScale = Math.max(0.5, Math.min(2.2, canvasScale.value * factor))
    if (Math.abs(nextScale - canvasScale.value) < 0.001) return
    canvasScale.value = nextScale

    const nextPointerX = worldX * nextScale
    const nextPointerY = worldY * nextScale
    board.scrollLeft += nextPointerX - pointerX
    board.scrollTop += nextPointerY - pointerY
  }

  function onBoardDrop(_event: DragEvent) {
    dragHoverTargetId.value = null
    // Node creation is now handled by clicking palette items and confirming config.
  }

  const PORT_RADIUS = 6

  function getPortPosition(id: string, side: 'input' | 'output', portIndex = 0) {
    return getNodePortPosition({
      node: nodes.value.find((n) => n.id === id),
      side,
      portIndex,
      cardWidth: CARD_WIDTH,
      cardHeight: CARD_HEIGHT,
      portRadius: PORT_RADIUS,
    })
  }

  function pruneInvalidLinksForNode(nodeId: string) {
    const node = nodes.value.find((item) => item.id === nodeId)
    if (!node) return false
    const before = links.value.length
    links.value = pruneLinksForNodePorts({
      links: links.value,
      nodeId,
      inputNum: node.inputNum,
      outputNum: node.outputNum,
    })
    return links.value.length !== before
  }

  function startLink(id: string, outputIndex: number, event: PointerEvent) {
    if (event.button !== 0) return
    const pos = getPortPosition(id, 'output', outputIndex)
    if (!pos) return
    linkSession.value = createBoardLinkSession({
      nodeId: id,
      outputIndex,
      pointerId: event.pointerId,
      position: pos,
    })
    window.addEventListener('pointermove', onLinkPointerMove)
    window.addEventListener('pointerup', onLinkPointerUp)
    window.addEventListener('blur', onLinkPointerUp)
    event.preventDefault()
    event.stopPropagation()
  }

  function onLinkPointerMove(event: PointerEvent) {
    const session = linkSession.value
    if (!session || event.pointerId !== session.pointerId) return
    const { x, y } = getCanvasPoint(event)
    session.currentX = x
    session.currentY = y
  }

  function clearLinkSession(event?: Event) {
    if (!linkSession.value) return
    linkSession.value = null
    window.removeEventListener('pointermove', onLinkPointerMove)
    window.removeEventListener('pointerup', onLinkPointerUp)
    window.removeEventListener('blur', onLinkPointerUp)
    if (event && event.cancelable) event.preventDefault()
  }

  function onLinkPointerUp(event: Event) {
    clearLinkSession(event)
  }

  function completeLink(targetId: string, inputIndex: number, event: PointerEvent) {
    const session = linkSession.value
    if (!session) return
    if (session.from.node === targetId) {
      clearLinkSession(event)
      return
    }
    const targetEndpoint = createBoardLinkTarget(targetId, inputIndex)
    if (boardLinkExists(links.value, session.from, targetEndpoint)) {
      clearLinkSession(event)
      return
    }
    links.value.push(createBoardLink(session.from, targetEndpoint))
    syncGraphSnapshot()
    void persistGraphConfig('complete_link')
    clearLinkSession(event)
  }

  async function addOutputRoute(sourceId: string) {
    const sourceNode = nodes.value.find((node) => node.id === sourceId)
    if (!sourceNode) return
    const targetNodes = nodes.value.filter((node) => node.id !== sourceId)
    if (!targetNodes.length) {
      lastError.value = 'Create another node before adding an output route.'
      return
    }

    const outputCount = normalizePortCount(sourceNode.outputNum, 1)
    for (let outputIndex = 0; outputIndex < outputCount; outputIndex += 1) {
      const from = { node: sourceId, index: outputIndex }
      for (const targetNode of targetNodes) {
        const inputCount = normalizePortCount(targetNode.inputNum, 1)
        for (let inputIndex = 0; inputIndex < inputCount; inputIndex += 1) {
          const to = { node: targetNode.id, index: inputIndex }
          if (boardLinkExists(links.value, from, to)) continue
          links.value.push(createBoardLink(from, to))
          syncGraphSnapshot()
          await persistGraphConfig('add_output_route')
          return
        }
      }
    }

    lastError.value = 'All available output routes already exist.'
  }

  async function updateOutputRoute(
    routeId: string,
    patch: { outputIndex?: number; targetNodeId?: string; inputIndex?: number },
  ) {
    const index = links.value.findIndex((link) => link.id === routeId)
    const existing = links.value[index]
    if (index < 0 || !existing) return
    const next = {
      ...existing,
      from: {
        ...existing.from,
        index: patch.outputIndex == null ? existing.from.index : Math.max(0, Math.floor(Number(patch.outputIndex) || 0)),
      },
      to: {
        node: patch.targetNodeId == null ? existing.to.node : String(patch.targetNodeId || '').trim(),
        index: patch.inputIndex == null ? existing.to.index : Math.max(0, Math.floor(Number(patch.inputIndex) || 0)),
      },
    }
    if (!next.to.node || next.to.node === next.from.node) return
    const duplicate = links.value.some(
      (link) =>
        link.id !== routeId &&
        link.from.node === next.from.node &&
        link.from.index === next.from.index &&
        link.to.node === next.to.node &&
        link.to.index === next.to.index,
    )
    if (duplicate) return
    links.value.splice(index, 1, next)
    syncGraphSnapshot()
    await persistGraphConfig('update_output_route')
  }

  async function removeOutputRoute(routeId: string) {
    const before = links.value.length
    links.value = links.value.filter((link) => link.id !== routeId)
    if (links.value.length === before) return
    syncGraphSnapshot()
    await persistGraphConfig('remove_output_route')
  }

  function buildPath(start: { x: number; y: number }, end: { x: number; y: number }) {
    return buildLinkPath(start, end)
  }

  function linkPath(link: LinkItem) {
    const start = getPortPosition(link.from.node, 'output', link.from.index)
    const end = getPortPosition(link.to.node, 'input', link.to.index)
    if (!start || !end) return ''
    return buildPath(start, end)
  }

  function activeLinkPath() {
    const session = linkSession.value
    if (!session) return ''
    const start = { x: session.startX, y: session.startY }
    const end = { x: session.currentX, y: session.currentY }
    return buildPath(start, end)
  }

  function onWindowResize() {
    ensurePositions()
  }

  function reselectExistingItems() {
    const valid = new Set<string>(nodes.value.map((n) => n.id))
    selectedItemIds.value = selectedItemIds.value.filter((id) => valid.has(id))
  }

  watch(
    () => nodes.value.length,
    () => {
      reselectExistingItems()
    },
  )

  onMounted(() => {
    ensurePositions()
    window.addEventListener('resize', onWindowResize)
    window.addEventListener('keydown', onWindowKeyDown)
    window.addEventListener('paste', onWindowPaste)
    listNodes()
      .then((items) => {
        availableNodes.value = items
      })
      .catch((e: any) => {
        lastError.value = String(e?.message || e)
      })
    syncGraphSnapshot()
    refreshNodeConfigs().catch(() => null)
    startGraphEventStream()
  })

  onBeforeUnmount(() => {
    stopActiveNodeRefresh()
    stopGraphEventStream()
    activeDragItemIds.clear()
    pendingUiPositions.clear()
    window.removeEventListener('resize', onWindowResize)
    window.removeEventListener('keydown', onWindowKeyDown)
    window.removeEventListener('paste', onWindowPaste)
    window.removeEventListener('mousemove', onPanMouseMove)
    window.removeEventListener('mouseup', onPanEnd)
    window.removeEventListener('blur', onPanEnd)
    window.removeEventListener('pointermove', onLinkPointerMove)
    window.removeEventListener('pointerup', onLinkPointerUp)
    window.removeEventListener('blur', onLinkPointerUp)
  })

  watch(
    () => graphLoadRequest.value,
    (config) => {
      if (!config) return
      applyGraphConfig(config)
      graphLoadRequest.value = null
      selectedItemIds.value = []
      refreshNodeConfigsAndMemory().catch(() => null)
      startGraphEventStream()
    },
  )

  watch(
    () => currentGraphId.value,
    () => {
      startGraphEventStream()
    },
  )

  watch(
    () => currentGraphWorkingPath.value,
    () => {
      syncGraphSnapshot()
    },
  )

  return {
    selectedNodeId,
    lastError,
    memoryMode,
    graphSnapshot,
    graphLoadRequest,
    currentGraphId,
    currentGraphName,
    currentGraphWorkingPath,

    availableNodes,
    nodes,
    links,
    nodeConfigs,

    boardRef,
    canvasRef,
    canvasScale,
    canvasWidth,
    canvasHeight,
    selectionRect,
    suppressClickUntil,
    dragSession,
    dragHoverTargetId,
    panSession,
    linkSession,

    nodeStates,
    nodeDonePulse,
    nodeRuns,
    selectedNodeWorkingPath,
    selectedNodeWorkingPathRevision,

    selectNode,
    openNodeSettings,
    openNodeFolder,
    openGraphPanel,
    triggerNode,
    startClockNode,
    sendNodeMessage,
    createNodeFromPalette,
    createNodeAtPosition,
    previewMessage,
    onNodePaletteDragStart,
    renameNodeCard,
    deleteNodeCard,
    ensureNodeConfig,
    refreshNodeConfig,
    setNodeFields,
    clearNodeFields,

    isDragging,
    isNodeSelected,
    itemStyle,
    onItemClick,
    onItemPointerDown,
    onItemPointerMove,
    endDrag,

    onBoardMouseDownCapture,
    onBoardWheel,
    onBoardDragOver,
    onBoardDrop,
    onNodeCardDragOver,
    onNodeCardDrop,
    onWindowResize,

    startLink,
    completeLink,
    linkPath,
    activeLinkPath,
    detachLinks,
    addOutputRoute,
    updateOutputRoute,
    removeOutputRoute,

    linkFlows,
    LINK_FLOW_DURATION_MS,
    LINK_FLOW_BUBBLES,

    isNodeRunning,
    isNodeWorking,
    isClockNode,
    isClockRunning,
    isNodeStopped,
    toggleNodeStop,
    stopNodeWork,
  }
}

