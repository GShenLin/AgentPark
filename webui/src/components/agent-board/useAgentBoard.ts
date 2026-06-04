import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  controlNodeInstance,
  createNodeInstance,
  deleteNodeInstance,
  emitGraph,
  getPasteAgentConfig,
  listNodeInstanceConfigs,
  listNodes,
  renameNodeInstance,
  saveGraph,
  setNodeInstanceState,
  startGraphRunner,
  updateNodeInstanceConfig,
  type GraphConfig,
  type GraphLinkEndpoint,
  type MessageEnvelope,
  type NodeInstanceConfig,
  type NodeInstanceState,
  type NodeInfo,
  type PasteAgentConfig,
} from '../../api'
import { resolveDroppedPaths } from '../../composables/droppedPaths'
import { useGlobalState } from '../../composables/useGlobalState'
import type { AgentBoardContext, DragSession, LinkItem, LinkSession, NodeCard, NodeRunState, PanSession } from './context'
import { normalizeRuntimeEvent, normalizeRuntimeEvents, normalizeRuntimeToolCalls } from './toolRuntimeEvents'

export function useAgentBoard(): AgentBoardContext {
  const {
    selectedNodeId,
    lastError,
    memoryMode,
    graphSnapshot,
    graphLoadRequest,
    currentGraphId,
    currentGraphName,
    nodeSettingsRequest,
    nodeEditorAttachments,
  } =
    useGlobalState()

  const boardRef = ref<HTMLElement | null>(null)
  const canvasRef = ref<HTMLElement | null>(null)
  const canvasScale = ref(1)
  const selectionRect = ref<{ x: number; y: number; width: number; height: number } | null>(null)
  const suppressClickUntil = ref(0)

  const selectedItemIds = ref<string[]>([])
  let selectionSession:
    | {
        startX: number
        startY: number
        currentX: number
        currentY: number
        additive: boolean
      }
    | null = null

  let dragBatchStart: Record<string, { x: number; y: number }> | null = null
  let activeDragItemIds = new Set<string>()
  const pendingUiPositions = new Map<string, { x: number; y: number }>()
  let pasteCount = 0
  let clipboardSnapshot: {
    nodes: NodeCard[]
    links: LinkItem[]
  } | null = null
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
    } else {
      return
    }
    nodeSettingsRequest.value = {
      id: targetId,
      nonce: Date.now(),
    }
  }

  function openEmptyBoardPanel() {
    selectedNodeId.value = null
    selectedItemIds.value = []
    memoryMode.value = 'graph'
    selectedNodeWorkingPath.value = ''
    selectedNodeWorkingPathRevision.value += 1
  }

  function traceBoardDrag(event: string, payload: Record<string, unknown>) {
    if (typeof window === 'undefined') return
    const entry = {
      ts: new Date().toISOString(),
      event,
      ...payload,
    }
    const bag = window as unknown as { __agentBoardDragTrace?: unknown[] }
    const trace = Array.isArray(bag.__agentBoardDragTrace) ? bag.__agentBoardDragTrace : []
    trace.push(entry)
    if (trace.length > 300) trace.shift()
    bag.__agentBoardDragTrace = trace
    console.debug('[board-drag]', entry)
  }

  function getClampedUiPosition(id: string) {
    const pos = getItemPosition(id)
    if (!pos) return null
    return {
      x: clampX(pos.x),
      y: Math.max(0, pos.y),
    }
  }

  function rememberPendingUiPositions(itemIds: Iterable<string>, reason: string) {
    for (const itemId of itemIds) {
      const pos = getClampedUiPosition(itemId)
      if (!pos) continue
      pendingUiPositions.set(itemId, pos)
      traceBoardDrag('ui_pending', { itemId, reason, x: pos.x, y: pos.y })
    }
  }

  function clearPendingUiPosition(itemId: string, reason: string) {
    if (!pendingUiPositions.has(itemId)) return
    pendingUiPositions.delete(itemId)
    traceBoardDrag('ui_pending_cleared', { itemId, reason })
  }

  function hasClipboardSnapshot() {
    return !!clipboardSnapshot && clipboardSnapshot.nodes.length > 0
  }

  function normalizePasteAgentConfig(raw: PasteAgentConfig | null | undefined): PasteAgentConfig {
    const cfg = raw || ({} as PasteAgentConfig)
    const toolsRaw = Array.isArray(cfg.tools) ? cfg.tools : []
    const safeTools: string[] = []
    const seen = new Set<string>()
    for (const item of toolsRaw) {
      const value = String(item || '').trim()
      if (!value) continue
      const key = value.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      safeTools.push(value)
    }
    return {
      agent_id: String(cfg.agent_id || 'pastagent').trim() || 'pastagent',
      name: String(cfg.name || 'PasteAgent').trim() || 'PasteAgent',
      provider_id: String(cfg.provider_id || '').trim(),
      mode: String(cfg.mode || 'chat').trim() || 'chat',
      web_search: normalizeSwitch(cfg.web_search, 'enabled'),
      thinking: normalizeSwitch(cfg.thinking, 'enabled'),
      system_prompt: String(cfg.system_prompt || ''),
      tools: safeTools,
    }
  }

  async function ensurePasteAgentConfigLoaded(forceReload = false) {
    if (!forceReload && pasteAgentConfigCache) return pasteAgentConfigCache
    try {
      const cfg = await getPasteAgentConfig()
      pasteAgentConfigCache = normalizePasteAgentConfig(cfg)
      return pasteAgentConfigCache
    } catch {
      pasteAgentConfigCache = normalizePasteAgentConfig(null)
      return pasteAgentConfigCache
    }
  }

  async function pasteClipboardTextAsAgent(rawText: string) {
    const text = String(rawText || '').trim()
    if (!text) return false
    const pasteCfg = await ensurePasteAgentConfigLoaded()
    const nodeName = String(pasteCfg.name || pasteCfg.agent_id || 'PasteAgent').trim() || 'PasteAgent'
    const nodeId = await createNodeFromPalette('agent_node', nodeName, {
      provider_id: pasteCfg.provider_id,
      system_prompt: pasteCfg.system_prompt,
      mode: pasteCfg.mode,
      web_search: normalizeSwitch(pasteCfg.web_search, 'enabled'),
      thinking: normalizeSwitch(pasteCfg.thinking, 'enabled'),
      tools: Array.isArray(pasteCfg.tools) ? pasteCfg.tools : [],
    })
    if (!nodeId) return false
    await sendNodeMessage(nodeId, text)
    return true
  }

  function previewMessage(value: string | null) {
    const text = String(value ?? '').trim()
    if (!text) return ''
    return text.length > 64 ? `${text.slice(0, 64)}...` : text
  }

  function messageToText(value: string | MessageEnvelope) {
    if (typeof value === 'string') return value
    const parts = Array.isArray(value?.parts) ? value.parts : []
    const output: string[] = []
    for (const part of parts) {
      if (!part || typeof part !== 'object') continue
      const typ = String((part as any).type || '').toLowerCase()
      if (typ === 'text') {
        const text = String((part as any).text || '')
        if (text) output.push(text)
      } else if (typ === 'resource') {
        const res = (part as any).resource || {}
        const kind = String(res.kind || 'file')
        const uri = String(res.uri || '')
        if (uri) output.push(`[${kind}] ${uri}`)
      }
    }
    return output.join('\n').trim()
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

  type BoardNodePlacement =
    | { kind: 'selection-anchor' }
    | {
        kind: 'fixed'
        ui: { x: number; y: number }
      }

  function sanitizeBoardPoint(ui: { x: number; y: number }) {
    return {
      x: clampX(Number(ui?.x ?? 0)),
      y: Math.max(0, Number(ui?.y ?? 0)),
    }
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
    const nodeId = makeUniqueId(requestedId)
    const graphId = currentGraphId.value || 'default'
    const ui = resolveNodePlacement(placement)

    await createNodeInstance(nodeId, safeTypeId, nodeId, graphId, ui)
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
      thinking: normalizeSwitch((fields as any)?.thinking, 'enabled'),
      systemPrompt: String((fields as any)?.system_prompt ?? ''),
      tools: Array.isArray((fields as any)?.tools) ? (fields as any).tools.map(String).filter(Boolean) : [],
      workingPath: String((fields as any)?.working_path ?? '').trim(),
    })
    selectedItemIds.value = [nodeId]
    selectedNodeId.value = nodeId
    memoryMode.value = 'agent'
    syncGraphSnapshot()
    await persistGraphConfig('create_node_from_palette')
    refreshNodeConfigs().catch(() => null)
    ensureNodeConfig(nodeId).catch(() => null)
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
    const node = nodes.value.find((item) => item.id === oldId)
    if (node) {
      node.id = newId
      node.name = newId
    }

    if (selectedNodeId.value === oldId) selectedNodeId.value = newId
    selectedItemIds.value = selectedItemIds.value.map((id) => (id === oldId ? newId : id))

    for (const link of links.value) {
      if (link.from.node === oldId) link.from.node = newId
      if (link.to.node === oldId) link.to.node = newId
    }

    const prevCfg = nodeConfigs.value[oldId]
    const nextCfg = { ...nodeConfigs.value }
    delete nextCfg[oldId]
    if (prevCfg) {
      nextCfg[newId] = {
        ...prevCfg,
        node_id: newId,
        name: newId,
      } as NodeInstanceConfig
    }
    nodeConfigs.value = nextCfg

    const prevState = nodeStates.value[oldId]
    const nextState = { ...nodeStates.value }
    delete nextState[oldId]
    if (prevState) nextState[newId] = prevState
    nodeStates.value = nextState

    const prevRun = nodeRuns.value[oldId]
    const nextRuns = { ...nodeRuns.value }
    delete nextRuns[oldId]
    if (prevRun) {
      nextRuns[newId] = { ...prevRun, nodeId: newId }
    }
    nodeRuns.value = nextRuns

    const prevPulse = nodeDonePulse.value[oldId]
    const nextPulse = { ...nodeDonePulse.value }
    delete nextPulse[oldId]
    if (typeof prevPulse === 'number') nextPulse[newId] = prevPulse
    nodeDonePulse.value = nextPulse
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
    refreshNodeConfigs().catch(() => null)
  }

  const CARD_WIDTH = 200
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

  function sleep(ms: number) {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }

  function clampX(value: number) {
    return Math.max(0, value)
  }

  function normalizePortCount(value: unknown, fallback = 1) {
    const num = Number(value)
    if (!Number.isFinite(num)) return fallback
    const intNum = Math.floor(num)
    return intNum > 0 ? intNum : fallback
  }

  function normalizePortIndex(value: unknown, fallback = 0) {
    const num = Number(value)
    if (!Number.isFinite(num)) return fallback
    const intNum = Math.floor(num)
    return intNum >= 0 ? intNum : fallback
  }

  function normalizeSwitch(value: unknown, fallback: 'enabled' | 'disabled'): 'enabled' | 'disabled' {
    const text = String(value ?? '').trim().toLowerCase()
    if (['enabled', 'enable', 'on', 'true', '1', 'yes'].includes(text)) return 'enabled'
    if (['disabled', 'disable', 'off', 'false', '0', 'no'].includes(text)) return 'disabled'
    return fallback
  }

  function isFileDropEvent(event: DragEvent) {
    const types = Array.from(event.dataTransfer?.types || [])
    return types.includes('application/x-aitools-file') || types.includes('Files')
  }

  function appendNodeEditorAttachment(path: string, name = '') {
    const safePath = String(path || '').trim()
    const safeName = String(name || '').trim() || safePath
    if (!safePath) return
    if (nodeEditorAttachments.value.some((item) => item.path === safePath)) return
    nodeEditorAttachments.value.push({ path: safePath, name: safeName })
  }

  function updateCanvasSize() {
    const nodePoints = nodes.value.map((n) => ({ x: n.ui.x, y: n.ui.y }))
    const points = nodePoints
    if (!points.length) {
      canvasWidth.value = 1400
      canvasHeight.value = 900
      return
    }
    const maxX = Math.max(...points.map((p) => p.x)) + CARD_WIDTH + BOARD_PADDING * 2
    const maxY = Math.max(...points.map((p) => p.y)) + CARD_HEIGHT + BOARD_PADDING * 2
    canvasWidth.value = Math.max(1000, Math.ceil(maxX))
    canvasHeight.value = Math.max(700, Math.ceil(maxY))
  }

  function ensurePositions() {
    const baseX = BOARD_PADDING
    const baseY = BOARD_PADDING
    let idx = 0
    for (const node of nodes.value) {
      if (node.ui) continue
      const col = idx % 4
      const row = Math.floor(idx / 4)
      node.ui = { x: baseX + col * (CARD_WIDTH + BOARD_GAP), y: baseY + row * (CARD_HEIGHT + BOARD_GAP) }
      idx += 1
    }
    updateCanvasSize()
  }

  function linkKey(from: { node: string; index: number }, to: { node: string; index: number }) {
    return `${from.node}:${from.index}->${to.node}:${to.index}`
  }

  function dedupeLinks(items: { id: string; from: { node: string; index: number }; to: { node: string; index: number } }[]) {
    const seen = new Set<string>()
    const out: { id: string; from: { node: string; index: number }; to: { node: string; index: number } }[] = []
    for (const link of items) {
      const key = linkKey(link.from, link.to)
      if (seen.has(key)) continue
      seen.add(key)
      out.push(link)
    }
    return out
  }

  function buildGraphSnapshot(): GraphConfig {
    return {
      id: currentGraphId.value || 'default',
      name: currentGraphName.value || 'default',
      nodes: nodes.value.map((node) => ({
          id: node.id,
          typeId: node.typeId,
          name: node.name,
          input_num: normalizePortCount(node.inputNum, 1),
          output_num: normalizePortCount(node.outputNum, 1),
          ui: { x: node.ui.x, y: node.ui.y },
          providerId: node.providerId,
          mode: node.mode,
          web_search: node.webSearch,
          thinking: node.thinking,
          systemPrompt: node.systemPrompt,
          tools: node.tools,
          workingPath: node.workingPath,
        })),
      links: dedupeLinks(
        links.value.map((link) => ({
          id: link.id,
          from: { node: link.from.node, index: normalizePortIndex(link.from.index, 0) },
          to: { node: link.to.node, index: normalizePortIndex(link.to.index, 0) },
        })),
      ),
    }
  }

  let graphSaveRunning = false
  let graphSavePending = false
  let graphSavePendingReason = 'unknown'

  function syncGraphSnapshot() {
    graphSnapshot.value = buildGraphSnapshot()
  }

  async function persistGraphConfig(reason = 'unknown') {
    const saveReason = String(reason || '').trim() || 'unknown'
    if (graphSaveRunning) {
      graphSavePending = true
      graphSavePendingReason = saveReason
      return
    }
    graphSaveRunning = true
    graphSavePending = false
    graphSavePendingReason = 'unknown'
    try {
      const snapshot = buildGraphSnapshot()
      const graphId = currentGraphId.value || snapshot.id || 'default'
      const payload: GraphConfig = {
        ...snapshot,
        id: graphId,
        name: currentGraphName.value || snapshot.name || graphId,
        source_graph_id: graphId,
      }
      await saveGraph(graphId, payload, { saveReason })
      if (typeof window !== 'undefined') {
        const event = {
          ts: new Date().toISOString(),
          reason: saveReason,
          graphId,
          nodesCount: Array.isArray(snapshot.nodes) ? snapshot.nodes.length : 0,
          linksCount: Array.isArray(snapshot.links) ? snapshot.links.length : 0,
        }
        const bag = window as unknown as { __graphSaveTrace?: any[] }
        const trace = Array.isArray(bag.__graphSaveTrace) ? bag.__graphSaveTrace : []
        trace.push(event)
        if (trace.length > 200) trace.shift()
        bag.__graphSaveTrace = trace
        console.debug('[graph-save]', event)
      }
    } catch (e: any) {
      lastError.value = String(e?.message || e)
    } finally {
      graphSaveRunning = false
      if (graphSavePending) {
        const pendingReason = graphSavePendingReason
        graphSavePendingReason = 'unknown'
        void persistGraphConfig(pendingReason)
      }
    }
  }

  function applyGraphConfig(config: GraphConfig) {
    const graphId = currentGraphId.value || config.id || 'default'
    activeDragItemIds.clear()
    pendingUiPositions.clear()
    selectedNodeId.value = null
    selectedNodeWorkingPath.value = ''
    selectedNodeWorkingPathRevision.value += 1
    nodes.value = []

    void startGraphRunner(graphId).catch(() => null)

    links.value = dedupeLinks(
      (config.links || [])
        .map((link) => {
          const fromRaw = (link as any).from
          const toRaw = (link as any).to
          let fromNode = ''
          let toNode = ''
          let fromIndex = 0
          let toIndex = 0

          if (fromRaw && typeof fromRaw === 'object') {
            fromNode = String((fromRaw as any).node || '').trim()
            fromIndex = normalizePortIndex((fromRaw as any).index, 0)
          } else {
            fromNode = String(fromRaw || '').trim()
          }

          if (toRaw && typeof toRaw === 'object') {
            toNode = String((toRaw as any).node || '').trim()
            toIndex = normalizePortIndex((toRaw as any).index, 0)
          } else {
            toNode = String(toRaw || '').trim()
          }

          return {
            id: link.id,
            from: { node: fromNode, index: fromIndex },
            to: { node: toNode, index: toIndex },
          }
        })
        .filter((link) => link.from.node && link.to.node),
    )

    updateCanvasSize()
    syncGraphSnapshot()
  }

  function detachLinks(id: string) {
    const before = links.value.length
    links.value = links.value.filter((link) => !(link.from.node === id || link.to.node === id))
    if (links.value.length !== before) {
      syncGraphSnapshot()
      void persistGraphConfig('detach_links')
    }
  }

  function deleteNodeCard(nodeId: string) {
    const index = nodes.value.findIndex((node) => node.id === nodeId)
    if (index === -1) return
    detachLinks(nodeId)
    stopNodeWork(nodeId)
    lastError.value = null
    const graphId = currentGraphId.value || 'default'
    deleteNodeInstance(nodeId, graphId).catch((e: any) => {
      lastError.value = String(e?.message || e)
    })
    nodes.value.splice(index, 1)
    selectedItemIds.value = selectedItemIds.value.filter((id) => id !== nodeId)
    if (selectedNodeId.value === nodeId) {
      selectedNodeId.value = null
    }

    const nextStates = { ...nodeStates.value }
    delete nextStates[nodeId]
    nodeStates.value = nextStates

    const nextDone = { ...nodeDonePulse.value }
    delete nextDone[nodeId]
    nodeDonePulse.value = nextDone

    nodeRuns.value = Object.fromEntries(Object.entries(nodeRuns.value).filter(([, run]) => run.nodeId !== nodeId))

    syncGraphSnapshot()
    void persistGraphConfig('delete_node_card')
  }

  function isDragging(id: string) {
    return dragSession.value?.itemId === id
  }

  function itemStyle(id: string) {
    const node = nodes.value.find((n) => n.id === id)
    const x = node?.ui?.x ?? 0
    const y = node?.ui?.y ?? 0
    return {
      left: `${x}px`,
      top: `${y}px`,
      zIndex: isDragging(id) ? 10 : 1,
    }
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
      ensureNodeConfig(id).catch(() => null)
    }
  }

  function onItemPointerDown(id: string, event: PointerEvent) {
    if (event.button !== 0) return
    const target = event.target as HTMLElement | null
    if (target?.closest('button, input, textarea, select, a')) return

    dragHoverTargetId.value = null
    const selected = new Set<string>(selectedItemIds.value)
    if (!selected.has(id)) {
      selected.clear()
      selected.add(id)
      selectedItemIds.value = Array.from(selected)
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
    const deadline = Date.now() + 60_000
    while (Date.now() < deadline) {
      const items = await listNodeInstanceConfigs(graphId).catch(() => null)
      const cfg = Array.isArray(items) ? (items as any[]).find((c) => String(c?.node_id || '') === nodeId) : null
      if (!cfg) {
        await sleep(250)
        continue
      }
      const state = String(cfg.state || 'idle')
      if (state === 'stop') return { status: 'stopped', message: '' }
      const runAt = String(cfg.last_run_at ?? '')
      const message = String(cfg.last_message ?? '')
      const pendingCount = Number((cfg as any)?.pending_count ?? 0)
      const hasInflight = !!(cfg as any)?.inflight
      const busy = state === 'working' || pendingCount > 0 || hasInflight
      if (runAt && (!prevRunAt || runAt !== prevRunAt)) {
        return { status: 'completed', message }
      }
      if (!runAt && !busy && message.trim() && message !== String(prevMessage ?? '')) {
        return { status: 'completed', message }
      }
      await sleep(250)
    }
    return { status: 'deadline', message: '' }
  }

  function triggerNodeDone(nodeId: string) {
    nodeDonePulse.value = { ...nodeDonePulse.value, [nodeId]: Date.now() }
  }

  function getNodeState(nodeId: string): NodeInstanceState {
    return nodeStates.value[nodeId] || 'idle'
  }

  function isNodeWorking(nodeId: string) {
    const state = getNodeState(nodeId)
    return state === 'working'
  }

  function isClockNode(nodeId: string) {
    const cfg = nodeConfigs.value[nodeId]
    const typeId = String(cfg?.type_id || nodes.value.find((n) => n.id === nodeId)?.typeId || '').trim()
    return typeId === 'clock_node'
  }

  function isClockRunning(nodeId: string) {
    if (!isClockNode(nodeId)) return false
    return !!nodeConfigs.value[nodeId]?.['_clock_running']
  }

  function isNodeStopped(nodeId: string) {
    return getNodeState(nodeId) === 'stop'
  }

  function isNodeRunning(nodeId: string) {
    void nodeId
    return false
  }

  function stopNodeWork(nodeId: string) {
    if (!isClockNode(nodeId)) return
    void toggleNodeStop(nodeId)
  }

  async function startClockNode(nodeId: string) {
    if (!isClockNode(nodeId)) return
    const graphId = currentGraphId.value || 'default'
    const res = await controlNodeInstance(nodeId, 'start', graphId)
    nodeStates.value = { ...nodeStates.value, [nodeId]: res.state }
    await startGraphRunner(graphId).catch(() => null)
    await refreshNodeConfigs().catch(() => null)
  }

  async function toggleNodeStop(nodeId: string) {
    const graphId = currentGraphId.value || 'default'
    if (isClockNode(nodeId)) {
      const action = getNodeState(nodeId) === 'stop' ? 'start' : 'stop'
      const res = await controlNodeInstance(nodeId, action, graphId)
      nodeStates.value = { ...nodeStates.value, [nodeId]: res.state }
      if (res.state === 'working') {
        await startGraphRunner(graphId).catch(() => null)
      }
      await refreshNodeConfigs().catch(() => null)
      return
    }
    const current = getNodeState(nodeId)
    const next: NodeInstanceState = current === 'stop' ? 'idle' : 'stop'
    await setNodeInstanceState(nodeId, next, graphId)
    nodeStates.value = { ...nodeStates.value, [nodeId]: next }
    if (next === 'idle') {
      startGraphRunner(graphId).catch(() => null)
    }
  }

  let nodeStatePollTimer: number | null = null

  async function refreshNodeConfigs() {
    const graphId = currentGraphId.value || 'default'
    const items = await listNodeInstanceConfigs(graphId)
    const next: Record<string, NodeInstanceState> = {}
    const nextConfigs: Record<string, NodeInstanceConfig> = {}
    const prevConfigs = nodeConfigs.value

    for (const cfg of items as NodeInstanceConfig[]) {
      const nodeId = String(cfg.node_id || '').trim()
      if (!nodeId) continue
      const typeId = String((cfg as any)?.type_id || '').trim()
      const uiCfg = (cfg as any)?.ui
      const serverUi = {
        x: clampX(Number(uiCfg?.x ?? 0)),
        y: Math.max(0, Number(uiCfg?.y ?? 0)),
      }
      let ui = serverUi
      const draggingLocally = activeDragItemIds.has(nodeId)
      const pendingUi = pendingUiPositions.get(nodeId)
      if (draggingLocally) {
        const localUi = getClampedUiPosition(nodeId)
        if (localUi) {
          ui = localUi
        }
      } else if (pendingUi) {
        if (pendingUi.x === serverUi.x && pendingUi.y === serverUi.y) {
          clearPendingUiPosition(nodeId, 'refresh_confirmed')
        } else {
          ui = pendingUi
        }
      }

      const existingNode = nodes.value.find((n) => n.id === nodeId)
      if (!existingNode) {
        nodes.value.push({
          id: nodeId,
          typeId: typeId || 'echo_node',
          name: String((cfg as any)?.name || nodeId),
          inputNum: normalizePortCount((cfg as any)?.input_num, 1),
          outputNum: normalizePortCount((cfg as any)?.output_num, 1),
          ui,
          last_message: String((cfg as any)?.last_message ?? '') || null,
          lastRuntimeEvent: normalizeRuntimeEvent((cfg as any)?.last_runtime_event),
          runtimeEvents: normalizeRuntimeEvents((cfg as any)?.runtime_events),
          runtimeToolCalls: normalizeRuntimeToolCalls((cfg as any)?.runtime_tool_calls),
          providerId: String((cfg as any)?.provider_id ?? '').trim(),
          mode: String((cfg as any)?.mode ?? '').trim(),
          webSearch: normalizeSwitch((cfg as any)?.web_search, 'disabled'),
          thinking: normalizeSwitch((cfg as any)?.thinking, 'enabled'),
          systemPrompt: String((cfg as any)?.system_prompt ?? ''),
          tools: Array.isArray((cfg as any)?.tools) ? (cfg as any).tools.map((item: unknown) => String(item)) : [],
          workingPath: String((cfg as any)?.working_path ?? '').trim(),
        })
      } else {
        existingNode.typeId = typeId || existingNode.typeId || 'echo_node'
        existingNode.name = String((cfg as any)?.name || existingNode.name || nodeId)
        existingNode.ui.x = ui.x
        existingNode.ui.y = ui.y
        existingNode.providerId = String((cfg as any)?.provider_id ?? existingNode.providerId ?? '').trim()
        existingNode.mode = String((cfg as any)?.mode ?? existingNode.mode ?? '').trim()
        existingNode.webSearch = normalizeSwitch((cfg as any)?.web_search ?? existingNode.webSearch, 'disabled')
        existingNode.thinking = normalizeSwitch((cfg as any)?.thinking ?? existingNode.thinking, 'enabled')
        existingNode.systemPrompt = String((cfg as any)?.system_prompt ?? existingNode.systemPrompt ?? '')
        existingNode.tools = Array.isArray((cfg as any)?.tools) ? (cfg as any).tools.map((item: unknown) => String(item)) : existingNode.tools || []
        existingNode.workingPath = String((cfg as any)?.working_path ?? existingNode.workingPath ?? '').trim()
        existingNode.lastRuntimeEvent = normalizeRuntimeEvent((cfg as any)?.last_runtime_event)
        existingNode.runtimeEvents = normalizeRuntimeEvents((cfg as any)?.runtime_events)
        existingNode.runtimeToolCalls = normalizeRuntimeToolCalls((cfg as any)?.runtime_tool_calls)
      }
    }

    const cfgIds = new Set<string>((items as NodeInstanceConfig[]).map((cfg) => String(cfg.node_id || '').trim()).filter(Boolean))
    if (cfgIds.size > 0) {
      nodes.value = nodes.value.filter((n) => cfgIds.has(n.id))
    }

    for (const cfg of items as NodeInstanceConfig[]) {
      const nodeId = String(cfg.node_id || '')
      if (!nodeId) continue
      nextConfigs[nodeId] = cfg
      const state = cfg.state
      next[nodeId] = state === 'working' || state === 'stop' ? state : 'idle'

      const prev = (prevConfigs as any)?.[nodeId]
      const prevRunAt = prev?.last_run_at != null ? String(prev.last_run_at) : ''
      const runAt = (cfg as any)?.last_run_at != null ? String((cfg as any).last_run_at) : ''
      const prevOut = prev?.last_message != null ? String(prev.last_message) : ''
      const out = (cfg as any)?.last_message != null ? String((cfg as any).last_message) : ''
      const runAtChanged = runAt !== prevRunAt
      const outputChanged = out !== prevOut
      const changed = runAtChanged || outputChanged
      const node = nodes.value.find((n) => n.id === nodeId)
      if (node) {
        node.inputNum = normalizePortCount((cfg as any)?.input_num, node.inputNum || 1)
        node.outputNum = normalizePortCount((cfg as any)?.output_num, node.outputNum || 1)
        if ((cfg as any)?.provider_id != null) {
          node.providerId = String((cfg as any).provider_id ?? '').trim()
        }
        if ((cfg as any)?.mode != null) {
          node.mode = String((cfg as any).mode ?? '').trim()
        }
        if ((cfg as any)?.web_search != null) {
          node.webSearch = normalizeSwitch((cfg as any).web_search, 'disabled')
        }
        if ((cfg as any)?.thinking != null) {
          node.thinking = normalizeSwitch((cfg as any).thinking, 'enabled')
        }
        if ((cfg as any)?.system_prompt != null) {
          node.systemPrompt = String((cfg as any).system_prompt ?? '')
        }
        if ((cfg as any)?.tools != null) {
          const tools = (cfg as any).tools
          node.tools = Array.isArray(tools) ? tools.map((item: unknown) => String(item)) : []
        }
        if ((cfg as any)?.working_path != null) {
          node.workingPath = String((cfg as any).working_path ?? '').trim()
        }
      }
      const nodeNeedsHydrate = node ? !String(node.last_message || '').trim() : false
      const shouldUpdatePreview = changed || nodeNeedsHydrate
      if (shouldUpdatePreview) {
        if (node) {
          node.last_message = out
          node.lastRuntimeEvent = normalizeRuntimeEvent((cfg as any)?.last_runtime_event)
          node.runtimeEvents = normalizeRuntimeEvents((cfg as any)?.runtime_events)
          node.runtimeToolCalls = normalizeRuntimeToolCalls((cfg as any)?.runtime_tool_calls)
          if (runAtChanged) triggerNodeDone(nodeId)
        }
      }
    }
    nodeStates.value = next
    nodeConfigs.value = nextConfigs
    if (selectedNodeId.value) {
      syncSelectedNodeWorkingPath(selectedNodeId.value)
    }
  }

  async function ensureNodeConfig(nodeId: string) {
    const graphId = currentGraphId.value || 'default'
    if (nodeConfigs.value[nodeId]) return
    const node = nodes.value.find((n) => n.id === nodeId)
    if (!node) return
    await createNodeInstance(node.id, node.typeId, node.name, graphId, node.ui).catch(() => null)
    await refreshNodeConfigs().catch(() => null)
  }

  async function triggerNode(nodeId: string) {
    const graphId = currentGraphId.value || 'default'
    const cfg = (nodeConfigs.value as any)?.[nodeId] || null
    const typeId = String(cfg?.type_id || nodes.value.find((n) => n.id === nodeId)?.typeId || '')
    if (typeId !== 'basic_trigger_node') return

    const prevRunAt = String(cfg?.last_run_at ?? '')
    const prevMessage = String(cfg?.last_message ?? '')
    await startGraphRunner(graphId).catch(() => null)
    await emitGraph(graphId, nodeId, '').catch(() => null)
    const waited = await waitForNodeOutput(nodeId, prevRunAt || null, prevMessage || null, graphId)
    if (waited.status === 'completed') {
      const node = nodes.value.find((n) => n.id === nodeId)
      if (node) node.last_message = waited.message
    }
  }

  async function sendNodeMessage(nodeId: string, message: string | MessageEnvelope) {
    const id = String(nodeId || '').trim()
    if (!id) return

    const text = messageToText(message)
    const cfg = (nodeConfigs.value as any)?.[id] || null
    const typeId = String(cfg?.type_id || nodes.value.find((n) => n.id === id)?.typeId || '')
    if (!typeId) return

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
    const graphId = currentGraphId.value || 'default'
    lastError.value = null
    try {
      const node = nodes.value.find((n) => n.id === id)
      if (node) node.last_message = text
      const prevRunAt = String(cfg?.last_run_at ?? '')
      const prevMessage = String(cfg?.last_message ?? '')
      await startGraphRunner(graphId).catch(() => null)
      await emitGraph(graphId, id, message)
      const waited = await waitForNodeOutput(id, prevRunAt || null, prevMessage || null, graphId)
      if (waited.status === 'completed') {
        const node = nodes.value.find((n) => n.id === id)
        if (node) node.last_message = waited.message
      }
    } catch (e: any) {
      lastError.value = String(e?.message || e)
    }
  }

  async function setNodeFields(nodeId: string, fields: Record<string, unknown>) {
    const graphId = currentGraphId.value || 'default'
    lastError.value = null
    await updateNodeInstanceConfig(nodeId, { fields }, graphId)
    const existing = nodeConfigs.value[nodeId]
    const base = existing || (() => {
      const node = nodes.value.find((n) => n.id === nodeId)
      return {
        node_id: nodeId,
        type_id: node?.typeId || '',
        name: node?.name || '',
        graph_id: graphId,
      } as NodeInstanceConfig
    })()
    const merged = {
      ...base,
      type_id: String((base as any)?.type_id || (nodes.value.find((n) => n.id === nodeId)?.typeId || '')),
      ...fields,
    } as NodeInstanceConfig
    nodeConfigs.value = { ...nodeConfigs.value, [nodeId]: merged }

    const node = nodes.value.find((item) => item.id === nodeId)
    if (node) {
      if (Object.prototype.hasOwnProperty.call(fields, 'provider_id')) {
        node.providerId = String((merged as any)?.provider_id ?? '').trim()
      }
      if (Object.prototype.hasOwnProperty.call(fields, 'mode')) {
        node.mode = String((merged as any)?.mode ?? '').trim()
      }
      if (Object.prototype.hasOwnProperty.call(fields, 'web_search')) {
        node.webSearch = normalizeSwitch((merged as any)?.web_search, 'disabled')
      }
      if (Object.prototype.hasOwnProperty.call(fields, 'thinking')) {
        node.thinking = normalizeSwitch((merged as any)?.thinking, 'enabled')
      }
      if (Object.prototype.hasOwnProperty.call(fields, 'system_prompt')) {
        node.systemPrompt = String((merged as any)?.system_prompt ?? '')
      }
      if (Object.prototype.hasOwnProperty.call(fields, 'tools')) {
        const tools = (merged as any)?.tools
        node.tools = Array.isArray(tools) ? tools.map((item: unknown) => String(item)) : []
      }
      if (Object.prototype.hasOwnProperty.call(fields, 'working_path')) {
        node.workingPath = String((merged as any)?.working_path ?? '').trim()
      }
    }

    if (selectedNodeId.value === nodeId) {
      syncSelectedNodeWorkingPath(nodeId)
    }

    await refreshNodeConfigs().catch(() => null)
    pruneInvalidLinksForNode(nodeId)
    syncGraphSnapshot()
    await persistGraphConfig('set_node_fields')
  }

  function startNodeStatePolling() {
    if (nodeStatePollTimer != null) {
      window.clearInterval(nodeStatePollTimer)
      nodeStatePollTimer = null
    }
    nodeStatePollTimer = window.setInterval(() => {
      refreshNodeConfigs().catch(() => null)
    }, 100)
    refreshNodeConfigs().catch(() => null)
  }

  function stopNodeStatePolling() {
    if (nodeStatePollTimer == null) return
    window.clearInterval(nodeStatePollTimer)
    nodeStatePollTimer = null
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
      const overItem = !!target?.closest('.node-card, .node-side-editor, .modal, .context-menu')
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
      const overItem = !!target?.closest('.node-card, .node-side-editor, .modal, .context-menu')
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
    if (isFileDropEvent(event)) {
      dragHoverTargetId.value = null
    }
  }

  function onNodeCardDragOver(id: string, event: DragEvent) {
    if (!isFileDropEvent(event)) return
    event.preventDefault()
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'copy'
    }
    dragHoverTargetId.value = String(id || '').trim() || null
  }

  async function onNodeCardDrop(nodeId: string, event: DragEvent) {
    const id = String(nodeId || '').trim()
    dragHoverTargetId.value = null
    if (!id || !isFileDropEvent(event)) return

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
        ensureNodeConfig(id).catch(() => null)
      }
    } catch (e: any) {
      lastError.value = String(e?.message || e)
    }
  }

  function getCanvasPoint(event: PointerEvent | DragEvent) {
    const canvas = canvasRef.value
    if (!canvas) return { x: 0, y: 0 }
    const rect = canvas.getBoundingClientRect()
    const style = window.getComputedStyle(canvas)
    const paddingLeft = Number.parseFloat(style.paddingLeft || '0') || 0
    const paddingTop = Number.parseFloat(style.paddingTop || '0') || 0
    const scale = canvasScale.value || 1
    return {
      x: (event.clientX - rect.left - paddingLeft) / scale,
      y: (event.clientY - rect.top - paddingTop) / scale,
    }
  }

  function getItemPosition(id: string) {
    const node = nodes.value.find((n) => n.id === id)
    if (node?.ui) return { x: node.ui.x, y: node.ui.y }
    return null
  }

  function updateSelectionRect() {
    const session = selectionSession
    if (!session) {
      selectionRect.value = null
      return
    }
    const x = Math.min(session.startX, session.currentX)
    const y = Math.min(session.startY, session.currentY)
    const width = Math.abs(session.currentX - session.startX)
    const height = Math.abs(session.currentY - session.startY)
    selectionRect.value = { x, y, width, height }
  }

  function computeItemsInRect(rect: { x: number; y: number; width: number; height: number }) {
    const selected = new Set<string>()
    const minX = rect.x
    const minY = rect.y
    const maxX = rect.x + rect.width
    const maxY = rect.y + rect.height
    const allIds = nodes.value.map((n) => n.id)
    for (const id of allIds) {
      const pos = getItemPosition(id)
      if (!pos) continue
      const left = pos.x
      const top = pos.y
      const right = pos.x + CARD_WIDTH
      const bottom = pos.y + CARD_HEIGHT
      const overlap = !(right < minX || left > maxX || bottom < minY || top > maxY)
      if (overlap) selected.add(id)
    }
    return selected
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
    if (rect && session && (rect.width > 3 || rect.height > 3)) {
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
    const selected = new Set<string>(selectedItemIds.value)
    if (!selected.size) return null
    const copiedNodes = nodes.value
      .filter((node) => selected.has(node.id))
      .map((node) => ({
        id: node.id,
        typeId: node.typeId,
        name: node.name,
        inputNum: node.inputNum,
        outputNum: node.outputNum,
        ui: { x: node.ui.x, y: node.ui.y },
        last_message: node.last_message,
        lastRuntimeEvent: null,
        runtimeEvents: [],
        providerId: node.providerId,
        mode: node.mode,
        webSearch: node.webSearch,
        thinking: node.thinking,
        systemPrompt: node.systemPrompt,
        tools: Array.isArray(node.tools) ? node.tools.map(String).filter(Boolean) : [],
        workingPath: node.workingPath,
      }))
    if (!copiedNodes.length) return null
    const copiedIds = new Set<string>(copiedNodes.map((n) => n.id))
    const copiedLinks = links.value
      .filter((link) => copiedIds.has(link.from.node) && copiedIds.has(link.to.node))
      .map((link) => ({
        id: link.id,
        from: { node: link.from.node, index: link.from.index },
        to: { node: link.to.node, index: link.to.index },
      }))
    return { nodes: copiedNodes, links: copiedLinks }
  }

  async function pasteSnapshot() {
    if (!hasClipboardSnapshot() || !clipboardSnapshot) return
    const graphId = currentGraphId.value || 'default'
    pasteCount += 1
    const offset = 36 * pasteCount
    const idMap = new Map<string, string>()
    const newNodes: NodeCard[] = []

    for (const node of clipboardSnapshot.nodes) {
      const nodeId = makeUniqueId(`${String(node.name || node.id || 'node').trim() || 'node'}1`)
      idMap.set(node.id, nodeId)
      const ui = { x: clampX(node.ui.x + offset), y: Math.max(0, node.ui.y + offset) }
      await createNodeInstance(nodeId, node.typeId, node.name, graphId, ui).catch(() => null)
      await updateNodeInstanceConfig(
        nodeId,
        {
          fields: {
            provider_id: node.providerId,
            system_prompt: node.systemPrompt,
            mode: node.mode,
            web_search: node.webSearch,
            thinking: node.thinking,
            tools: node.tools,
            working_path: node.workingPath,
          },
        },
        graphId,
      ).catch(() => null)
      newNodes.push({
        id: nodeId,
        typeId: node.typeId,
        name: node.name,
        inputNum: node.inputNum,
        outputNum: node.outputNum,
        ui,
        last_message: null,
        lastRuntimeEvent: null,
        runtimeEvents: [],
        providerId: node.providerId,
        mode: node.mode,
        webSearch: node.webSearch,
        thinking: node.thinking,
        systemPrompt: node.systemPrompt,
        tools: Array.isArray(node.tools) ? [...node.tools] : [],
        workingPath: node.workingPath,
      })
    }

    nodes.value.push(...newNodes)

    for (const link of clipboardSnapshot.links) {
      const fromId = idMap.get(link.from.node)
      const toId = idMap.get(link.to.node)
      if (!fromId || !toId) continue
      links.value.push({
        id: `link-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        from: { node: fromId, index: link.from.index },
        to: { node: toId, index: link.to.index },
      })
    }

    selectedItemIds.value = newNodes.map((node) => node.id)
    if (selectedItemIds.value.length === 1) {
      const selectedId = selectedItemIds.value[0]
      if (selectedId) {
        if (nodes.value.some((node) => node.id === selectedId)) {
          selectNode(selectedId)
        }
      }
    }
    updateCanvasSize()
    syncGraphSnapshot()
    await persistGraphConfig('paste_snapshot')
    refreshNodeConfigs().catch(() => null)
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
    if (key === 'v') {
      if (hasClipboardSnapshot()) {
        void pasteSnapshot()
        event.preventDefault()
      }
    }
  }

  function onWindowPaste(event: ClipboardEvent) {
    const target = event.target as HTMLElement | null
    if (target?.closest('input, textarea, [contenteditable="true"], select')) return

    if (hasClipboardSnapshot()) {
      event.preventDefault()
      void pasteSnapshot()
      return
    }

    const text = String(event.clipboardData?.getData('text/plain') || '')
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
    const offsetX = side === 'input' ? -PORT_RADIUS : CARD_WIDTH + PORT_RADIUS
    const node = nodes.value.find((n) => n.id === id)
    if (!node?.ui) return null
    const portCount = side === 'input' ? normalizePortCount(node.inputNum, 1) : normalizePortCount(node.outputNum, 1)
    const idx = Math.min(Math.max(0, portIndex), portCount - 1)
    const ratio = (idx + 0.5) / portCount
    return {
      x: node.ui.x + offsetX,
      y: node.ui.y + CARD_HEIGHT * ratio,
    }
  }

  function pruneInvalidLinksForNode(nodeId: string) {
    const node = nodes.value.find((item) => item.id === nodeId)
    if (!node) return false
    const maxInputs = normalizePortCount(node.inputNum, 1)
    const maxOutputs = normalizePortCount(node.outputNum, 1)
    const before = links.value.length
    links.value = links.value.filter((link) => {
      if (link.from.node === nodeId && normalizePortIndex(link.from.index, 0) >= maxOutputs) {
        return false
      }
      if (link.to.node === nodeId && normalizePortIndex(link.to.index, 0) >= maxInputs) {
        return false
      }
      return true
    })
    return links.value.length !== before
  }

  function startLink(id: string, outputIndex: number, event: PointerEvent) {
    if (event.button !== 0) return
    const pos = getPortPosition(id, 'output', outputIndex)
    if (!pos) return
    linkSession.value = {
      from: { node: id, index: normalizePortIndex(outputIndex, 0) },
      pointerId: event.pointerId,
      startX: pos.x,
      startY: pos.y,
      currentX: pos.x,
      currentY: pos.y,
    }
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
    const targetEndpoint: GraphLinkEndpoint = { node: targetId, index: normalizePortIndex(inputIndex, 0) }
    if (links.value.some((link) => link.from.node === session.from.node && link.from.index === session.from.index && link.to.node === targetEndpoint.node && link.to.index === targetEndpoint.index)) {
      clearLinkSession(event)
      return
    }
    links.value.push({
      id: `link-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      from: session.from,
      to: targetEndpoint,
    })
    syncGraphSnapshot()
    void persistGraphConfig('complete_link')
    clearLinkSession(event)
  }

  function buildPath(start: { x: number; y: number }, end: { x: number; y: number }) {
    const dx = end.x - start.x
    const c1 = start.x + dx * 0.4
    const c2 = start.x + dx * 0.6
    return `M ${start.x} ${start.y} C ${c1} ${start.y}, ${c2} ${end.y}, ${end.x} ${end.y}`
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
    startNodeStatePolling()
  })

  onBeforeUnmount(() => {
    stopNodeStatePolling()
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
      refreshNodeConfigs().catch(() => null)
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
    setNodeFields,

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
