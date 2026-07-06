import { computed, onBeforeUnmount, ref } from 'vue'
import {
  createGraphFromProfile,
  clearNodeInstanceMemory,
  cloneNodeInstance,
  controlNodeInstance,
  createNodeInstance,
  deleteGraph,
  deleteMobileNodeMessage,
  deleteNodeInstance,
  getMobileNodeConversation,
  emitGraph,
  graphEventsStreamUrl,
  listAgentProfiles,
  listGraphProfiles,
  listNodes,
  listNodeInstanceConfigs,
  listMobileGraphs,
  listMobileNodes,
  listMobilePcs,
  listProviders,
  listTools,
  loadGraph,
  nodeInstanceLiveStreamUrl,
  renameNodeInstance,
  saveGraph,
  sendMobileNodeMessage,
  setStartupGraphConfig,
  startGraphRunner,
  updateNodeInstanceConfig,
  type GraphConfig,
  type GraphOutputRoutes,
  type AgentProfile,
  type GraphProfile,
  type MessageEnvelope,
  type MobileGraph,
  type MobileGraphInstance,
  type MobileNode,
  type MobileNodeConversation,
  type MobilePc,
  type NodeInfo,
  type NodeInstanceConfig,
  type ProviderInfo,
} from '../api'
import { useGlobalState } from '../composables/useGlobalState'
import { messageText } from './mobileMessageRender'

export type MobileView = 'pcs' | 'graphs' | 'nodes' | 'chat'

export type MobileOutputRouteRow = {
  id: string
  outputIndex: number
  targetNodeId: string
  inputIndex: number
}

type MobileOutputRouteKeyInput = {
  outputIndex: number
  targetNodeId: string
  inputIndex: number
}

type MobileGraphSelection = {
  pcId: string
  graphId: string
}

type MobileChatSelection = MobileGraphSelection & {
  nodeId: string
}

const chatConversationRefreshEvents = new Set([
  'tool_call_start',
  'tool_call_end',
  'node_message_done',
  'node_output',
  'node_input',
])

const chatNodeRefreshGraphEvents = new Set([
  'emit_enqueued',
  'pending_enqueue_api',
  'node_dequeue',
  'node_output',
  'node_error',
  'node_state_set',
  'node_message_done',
  'node_stop_completed',
  'runtime_notice',
  'tool_call_start',
  'tool_call_end',
  'node_control',
  'node_created',
  'node_deleted',
  'node_renamed',
  'node_cloned',
  'node_config_updated',
  'node_memory_cleared',
  'node_working_recovered',
  'node_goal_evaluated',
  'node_goal_blocked',
  'node_goal_evaluation_failed',
  'event_dispatch_enqueue',
  'propagate_enqueue',
  'graph_save_api',
  'startup_node_state_recovered',
])

const chatConversationGraphEvents = new Set([
  'tool_call_start',
  'tool_call_end',
  'node_message_done',
  'node_output',
  'node_input',
  'node_error',
  'node_memory_cleared',
])

const chatLightweightGraphEvents = new Set([
  'emit_enqueued',
  'pending_enqueue_api',
  'node_dequeue',
  'node_state_set',
  'tool_call_start',
  'tool_call_end',
  'node_message_done',
  'node_output',
  'node_input',
  'node_stop_completed',
  'runtime_notice',
  'node_control',
  'node_goal_evaluated',
  'node_goal_blocked',
  'node_goal_evaluation_failed',
  'event_dispatch_enqueue',
  'propagate_enqueue',
  'startup_node_state_recovered',
])

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function messagesContainCommittedLive(messages: MessageEnvelope[], text: string, traceId: string): boolean {
  const safeTraceId = String(traceId || '').trim()
  if (safeTraceId && messages.some((message) => String(message?.trace_id || '').trim() === safeTraceId)) return true
  const safeText = String(text || '').trim()
  if (!safeText) return false
  return messages.some((message) => {
    const role = String(message?.role || '').trim().toLowerCase()
    return role !== 'user' && messageText(message) === safeText
  })
}

function portIndex(value: unknown, fallback: number) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.max(0, Math.floor(parsed))
}

function portCount(value: unknown, fallback: number) {
  return Math.max(1, portIndex(value, fallback))
}

function routeKey(row: MobileOutputRouteKeyInput) {
  return `${portIndex(row.outputIndex, 0)}:${String(row.targetNodeId || '').trim()}:${portIndex(row.inputIndex, 0)}`
}

function normalizeOutputRoutes(rawRoutes: unknown): GraphOutputRoutes {
  if (!rawRoutes || typeof rawRoutes !== 'object' || Array.isArray(rawRoutes)) return {}
  const next: GraphOutputRoutes = {}
  for (const [sourceIdRaw, routesRaw] of Object.entries(rawRoutes as Record<string, unknown>)) {
    const sourceId = String(sourceIdRaw || '').trim()
    if (!sourceId || !Array.isArray(routesRaw)) continue
    const routes = []
    for (const route of routesRaw) {
      if (!route || typeof route !== 'object') continue
      const outputIndex = portIndex((route as any).output_index, 0)
      const targetsRaw = (route as any).targets
      if (!Array.isArray(targetsRaw)) continue
      const targets = []
      const seenTargets = new Set<string>()
      for (const target of targetsRaw) {
        if (!target || typeof target !== 'object') continue
        const nodeId = String((target as any).node_id || '').trim()
        if (!nodeId || nodeId === sourceId) continue
        const inputIndex = portIndex((target as any).input_index, 0)
        const key = `${nodeId}:${inputIndex}`
        if (seenTargets.has(key)) continue
        seenTargets.add(key)
        targets.push({ node_id: nodeId, input_index: inputIndex })
      }
      if (targets.length) routes.push({ output_index: outputIndex, targets })
    }
    if (routes.length) {
      routes.sort((a, b) => a.output_index - b.output_index)
      next[sourceId] = routes
    }
  }
  return next
}

function normalizeGraphConfig(graph: GraphConfig): GraphConfig {
  return {
    ...graph,
    nodes: Array.isArray(graph.nodes) ? graph.nodes : [],
    output_routes: normalizeOutputRoutes(graph.output_routes),
  }
}

function flattenOutputRoutes(routes: GraphOutputRoutes, sourceNodeId: string): MobileOutputRouteRow[] {
  const sourceId = String(sourceNodeId || '').trim()
  if (!sourceId) return []
  const normalized = normalizeOutputRoutes(routes)
  const rows: MobileOutputRouteRow[] = []
  for (const route of normalized[sourceId] || []) {
    const outputIndex = portIndex(route.output_index, 0)
    for (const target of route.targets || []) {
      const targetNodeId = String(target.node_id || '').trim()
      if (!targetNodeId || targetNodeId === sourceId) continue
      const inputIndex = portIndex(target.input_index, 0)
      rows.push({
        id: `route-${sourceId}-${outputIndex}-${targetNodeId}-${inputIndex}`,
        outputIndex,
        targetNodeId,
        inputIndex,
      })
    }
  }
  return rows.sort((a, b) => {
    if (a.outputIndex !== b.outputIndex) return a.outputIndex - b.outputIndex
    if (a.targetNodeId !== b.targetNodeId) return a.targetNodeId.localeCompare(b.targetNodeId)
    return a.inputIndex - b.inputIndex
  })
}

function buildOutputRoutes(
  sourceNodeId: string,
  rows: MobileOutputRouteRow[],
  existingRoutes: GraphOutputRoutes,
): GraphOutputRoutes {
  const sourceId = String(sourceNodeId || '').trim()
  if (!sourceId) return normalizeOutputRoutes(existingRoutes)
  const next: GraphOutputRoutes = { ...normalizeOutputRoutes(existingRoutes) }
  const byOutput = new Map<number, Array<{ node_id: string; input_index: number }>>()
  const seenRows = new Set<string>()
  for (const row of rows) {
    const targetNodeId = String(row.targetNodeId || '').trim()
    if (!targetNodeId || targetNodeId === sourceId) continue
    const outputIndex = portIndex(row.outputIndex, 0)
    const inputIndex = portIndex(row.inputIndex, 0)
    const key = `${outputIndex}:${targetNodeId}:${inputIndex}`
    if (seenRows.has(key)) continue
    seenRows.add(key)
    const targets = byOutput.get(outputIndex) || []
    targets.push({ node_id: targetNodeId, input_index: inputIndex })
    byOutput.set(outputIndex, targets)
  }

  if (byOutput.size === 0) {
    delete next[sourceId]
    return next
  }

  next[sourceId] = Array.from(byOutput.entries())
    .sort(([left], [right]) => left - right)
    .map(([outputIndex, targets]) => ({
      output_index: outputIndex,
      targets: targets.sort((a, b) => {
        if (a.node_id !== b.node_id) return a.node_id.localeCompare(b.node_id)
        return a.input_index - b.input_index
      }),
    }))
  return next
}

function pruneOutputRoutesForNode(routes: GraphOutputRoutes, nodeId: string): GraphOutputRoutes {
  const removedNodeId = String(nodeId || '').trim()
  const normalized = normalizeOutputRoutes(routes)
  if (!removedNodeId) return normalized
  const next: GraphOutputRoutes = {}
  for (const [sourceId, sourceRoutes] of Object.entries(normalized)) {
    if (sourceId === removedNodeId) continue
    const prunedRoutes = []
    for (const route of sourceRoutes) {
      const targets = route.targets.filter((target) => target.node_id !== removedNodeId)
      if (targets.length) prunedRoutes.push({ ...route, targets })
    }
    if (prunedRoutes.length) next[sourceId] = prunedRoutes
  }
  return next
}

export function useMobileWorkspace() {
  const { nodeTriggerInputs } = useGlobalState()
  const view = ref<MobileView>('pcs')
  const pcs = ref<MobilePc[]>([])
  const graphInstances = ref<MobileGraphInstance[]>([])
  const nodes = ref<MobileNode[]>([])
  const graphConfig = ref<GraphConfig | null>(null)
  const nodeConfigs = ref<Record<string, NodeInstanceConfig>>({})
  const availableNodeTypes = ref<NodeInfo[]>([])
  const agentProfiles = ref<AgentProfile[]>([])
  const graphProfiles = ref<GraphProfile[]>([])
  const providers = ref<ProviderInfo[]>([])
  const availableTools = ref<string[]>([])
  const conversation = ref<MobileNodeConversation | null>(null)
  const selectedPc = ref<MobilePc | null>(null)
  const selectedGraph = ref<MobileGraph | null>(null)
  const selectedNode = ref<MobileNode | null>(null)
  const loading = ref(false)
  const sending = ref(false)
  const error = ref('')
  let chatLiveEventSource: EventSource | null = null
  let chatLiveStreamKey = ''
  let graphEventSource: EventSource | null = null
  let graphEventStreamKey = ''
  let graphRefreshTimer: number | null = null
  let graphRefreshInFlight = false
  let graphRefreshNeedsConversation = false
  let graphRefreshNeedsGraphConfig = false
  let pendingConversationLiveText = ''
  let pendingConversationLiveTraceId = ''

  const flatGraphs = computed(() => graphInstances.value.flatMap((item) => item.graphs))
  const selectedConfig = computed(() => {
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!nodeId) return null
    return nodeConfigs.value[nodeId] || null
  })
  const selectedNodeOutputRoutes = computed<MobileOutputRouteRow[]>(() => {
    const sourceNodeId = String(selectedNode.value?.id || '').trim()
    if (!sourceNodeId) return []
    return flattenOutputRoutes(graphConfig.value?.output_routes || {}, sourceNodeId)
  })

  let loadRequestId = 0

  function errorText(value: unknown) {
    return String((value as { message?: unknown })?.message || value || '')
  }

  function setError(value: unknown) {
    error.value = errorText(value)
  }

  function mergeNodeConfig(nodeId: string, patch: Record<string, unknown>) {
    const safeNodeId = String(nodeId || '').trim()
    if (!safeNodeId) return
    const existing = nodeConfigs.value[safeNodeId]
    nodeConfigs.value = {
      ...nodeConfigs.value,
      [safeNodeId]: {
        ...(existing || ({ node_id: safeNodeId, type_id: '' } as NodeInstanceConfig)),
        ...(patch as Partial<NodeInstanceConfig>),
        node_id: safeNodeId,
      } as NodeInstanceConfig,
    }
  }

  function currentGraphSelection(): MobileGraphSelection | null {
    const pcId = String(selectedPc.value?.id || '').trim()
    const graphId = String(selectedGraph.value?.id || '').trim()
    if (!pcId || !graphId) return null
    return { pcId, graphId }
  }

  function requireGraphSelection(): MobileGraphSelection {
    const selection = currentGraphSelection()
    if (!selection) throw new Error('PC and Graph selection are required')
    return selection
  }

  function requireChatSelection(): MobileChatSelection {
    const graphSelection = requireGraphSelection()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!nodeId) throw new Error('PC, Graph, and Node selection are required')
    return { ...graphSelection, nodeId }
  }

  function isCurrentGraphSelection(selection: MobileGraphSelection) {
    return (
      String(selectedPc.value?.id || '').trim() === selection.pcId &&
      String(selectedGraph.value?.id || '').trim() === selection.graphId
    )
  }

  function isCurrentChatSelection(selection: MobileChatSelection) {
    return isCurrentGraphSelection(selection) && String(selectedNode.value?.id || '').trim() === selection.nodeId
  }

  function applyNodes(nextNodes: MobileNode[]) {
    nodes.value = nextNodes
    if (selectedNode.value) {
      const current = nodes.value.find((item) => item.id === selectedNode.value?.id)
      if (current) selectedNode.value = current
    }
  }

  function mergeMobileNodeSummary(nodeId: string, patch: Partial<MobileNode>) {
    const safeNodeId = String(nodeId || '').trim()
    if (!safeNodeId) return
    nodes.value = nodes.value.map((node) => (node.id === safeNodeId ? { ...node, ...patch } : node))
    if (selectedNode.value?.id === safeNodeId) {
      selectedNode.value = { ...selectedNode.value, ...patch }
    }
  }

  async function refreshNodesForSelection(selection: MobileGraphSelection) {
    const nextNodes = await listMobileNodes(selection.pcId, selection.graphId)
    if (!isCurrentGraphSelection(selection)) return
    applyNodes(nextNodes)
  }

  async function waitForNodeOutputFromSummary(
    selection: MobileGraphSelection,
    nodeId: string,
    prevRunAt: string | null,
    prevMessage: string | null,
  ) {
    const timeoutMs = 60_000
    const pollMs = 250
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      const nextNodes = await listMobileNodes(selection.pcId, selection.graphId)
      if (!isCurrentGraphSelection(selection)) return { status: 'deadline' as const, message: '' }
      applyNodes(nextNodes)
      const current = nextNodes.find((item) => String(item.id || '') === nodeId)
      if (!current) {
        await sleep(pollMs)
        continue
      }
      const state = String(current.state || 'idle')
      if (state === 'stop') return { status: 'stopped' as const, message: '' }
      const runAt = String(current.last_run_at ?? '')
      const message = String(current.last_message ?? '')
      const pendingCount = Number(current.pending_count ?? 0)
      const busy = state === 'working' || pendingCount > 0
      if (runAt && (!prevRunAt || runAt !== prevRunAt)) {
        return { status: 'completed' as const, message }
      }
      if (!runAt && !busy && message.trim() && message !== String(prevMessage ?? '')) {
        return { status: 'completed' as const, message }
      }
      await sleep(pollMs)
    }
    return { status: 'deadline' as const, message: '' }
  }

  function rememberConversationCommit(text: string, traceId: string) {
    const safeText = String(text || '').trim()
    if (!safeText) return
    pendingConversationLiveText = safeText
    pendingConversationLiveTraceId = String(traceId || '').trim()
  }

  function clearConversationCommit() {
    pendingConversationLiveText = ''
    pendingConversationLiveTraceId = ''
  }

  function normalizeConversationAfterRefresh(nextConversation: MobileNodeConversation) {
    const messages = Array.isArray(nextConversation.messages) ? nextConversation.messages : []
    if (messagesContainCommittedLive(messages, pendingConversationLiveText, pendingConversationLiveTraceId)) {
      clearConversationCommit()
      return { ...nextConversation, live_message: '', thinking_message: '' }
    }
    if (pendingConversationLiveText && !String(nextConversation.live_message || '').trim()) {
      return { ...nextConversation, live_message: pendingConversationLiveText }
    }
    return nextConversation
  }

  async function refreshConversationForSelection(selection: MobileChatSelection) {
    const nextConversation = await getMobileNodeConversation(selection.pcId, selection.graphId, selection.nodeId)
    if (!isCurrentChatSelection(selection)) return
    conversation.value = normalizeConversationAfterRefresh(nextConversation)
  }

  function applySentMessageSnapshot(
    selection: MobileChatSelection,
    snapshot: { node?: MobileNode; conversation?: MobileNodeConversation },
  ) {
    if (!isCurrentChatSelection(selection)) return
    const nextNode = snapshot.node
    if (nextNode) {
      const index = nodes.value.findIndex((item) => item.id === nextNode.id)
      if (index >= 0) {
        nodes.value.splice(index, 1, nextNode)
      } else {
        nodes.value.push(nextNode)
      }
      if (selectedNode.value?.id === nextNode.id) selectedNode.value = nextNode
    }
    if (snapshot.conversation) {
      conversation.value = normalizeConversationAfterRefresh(snapshot.conversation)
    }
  }

  async function loadPcs() {
    const requestId = ++loadRequestId
    stopPolling()
    view.value = 'pcs'
    selectedPc.value = null
    selectedGraph.value = null
    selectedNode.value = null
    graphInstances.value = []
    nodes.value = []
    graphConfig.value = null
    nodeConfigs.value = {}
    conversation.value = null
    error.value = ''
    loading.value = true
    try {
      const nextPcs = await listMobilePcs()
      if (requestId !== loadRequestId) return
      pcs.value = nextPcs
    } catch (e) {
      if (requestId !== loadRequestId) return
      setError(e)
    } finally {
      if (requestId === loadRequestId) loading.value = false
    }
  }

  async function loadEditorCatalog() {
    if (providers.value.length && availableTools.value.length && availableNodeTypes.value.length) return
    await refreshEditorCatalog()
  }

  async function refreshEditorCatalog() {
    const [nextProviders, nextTools, nextNodeTypes] = await Promise.all([
      listProviders(),
      listTools(),
      listNodes(),
    ])
    providers.value = nextProviders
    availableTools.value = nextTools
    availableNodeTypes.value = nextNodeTypes
  }

  async function refreshAgentProfiles() {
    agentProfiles.value = await listAgentProfiles()
  }

  async function refreshGraphProfiles() {
    graphProfiles.value = await listGraphProfiles()
  }

  async function selectPc(pc: MobilePc) {
    const requestId = ++loadRequestId
    const pcId = String(pc.id || '').trim()
    if (!pcId) throw new Error('PC id is required')
    stopPolling()
    selectedPc.value = pc
    selectedGraph.value = null
    selectedNode.value = null
    nodes.value = []
    graphConfig.value = null
    nodeConfigs.value = {}
    conversation.value = null
    view.value = 'graphs'
    error.value = ''
    loading.value = true
    try {
      const [nextGraphInstances, nextGraphProfiles] = await Promise.all([
        listMobileGraphs(pcId),
        listGraphProfiles(),
      ])
      if (requestId !== loadRequestId) return
      graphInstances.value = nextGraphInstances
      graphProfiles.value = nextGraphProfiles
    } catch (e) {
      if (requestId !== loadRequestId) return
      setError(e)
    } finally {
      if (requestId === loadRequestId) loading.value = false
    }
  }

  async function refreshNodes() {
    await refreshNodesForSelection(requireGraphSelection())
  }

  async function refreshSelectedNodeConfig() {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!graphId) throw new Error('Graph selection is required')
    if (!nodeId) throw new Error('Node selection is required')
    const response = await listNodeInstanceConfigs(graphId)
    const configs = response.nodes || []
    const selected = configs.find((item) => String(item.node_id || '').trim() === nodeId)
    if (!selected) return
    nodeConfigs.value = {
      ...nodeConfigs.value,
      [nodeId]: selected,
    }
  }

  async function refreshGraphConfig() {
    const graphId = String(selectedGraph.value?.id || '').trim()
    if (!graphId) throw new Error('Graph selection is required')
    const graph = await loadGraph(graphId)
    graphConfig.value = normalizeGraphConfig(graph)
  }

  async function saveGraphByName(name: string) {
    const graphName = String(name || '').trim()
    if (!graphName) throw new Error('GraphName is required')
    error.value = ''
    loading.value = true
    try {
      const payload: GraphConfig = {
        id: graphName,
        name: graphName,
        nodes: [],
        output_routes: {},
      }
      const result = await saveGraph(graphName, payload, { saveReason: 'mobile_save_graph' })
      graphConfig.value = normalizeGraphConfig(payload)
      await setStartupGraphConfig(result.id, result.name).catch(() => null)
      const pc = selectedPc.value
      if (pc) {
        graphInstances.value = await listMobileGraphs(pc.id)
      }
      return result
    } catch (e) {
      setError(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function deleteGraphById(graphId: string) {
    const safeGraphId = String(graphId || '').trim()
    if (!safeGraphId) throw new Error('Graph id is required')
    error.value = ''
    loading.value = true
    try {
      await deleteGraph(safeGraphId)
      if (selectedGraph.value?.id === safeGraphId) {
        selectedGraph.value = null
        selectedNode.value = null
        nodes.value = []
        graphConfig.value = null
        nodeConfigs.value = {}
        conversation.value = null
        view.value = 'graphs'
        await setStartupGraphConfig('default', 'default').catch(() => null)
      }
      const pc = selectedPc.value
      if (pc) {
        graphInstances.value = await listMobileGraphs(pc.id)
      }
    } catch (e) {
      setError(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function createGraphFromPreset(profileId: string, graphId: string) {
    const safeProfileId = String(profileId || '').trim()
    const safeGraphId = String(graphId || '').trim()
    if (!safeProfileId || !safeGraphId) throw new Error('Graph preset and GraphID are required')
    error.value = ''
    loading.value = true
    try {
      const result = await createGraphFromProfile(safeProfileId, safeGraphId)
      const graph = normalizeGraphConfig(result.graph)
      await setStartupGraphConfig(graph.id, graph.name || graph.id).catch(() => null)
      const pc = selectedPc.value
      if (pc) {
        graphInstances.value = await listMobileGraphs(pc.id)
      }
      const createdGraph = graphInstances.value.flatMap((item) => item.graphs).find((item) => item.id === graph.id)
      if (createdGraph) {
        await selectGraph(createdGraph)
      }
      return { graph, selected: Boolean(createdGraph) }
    } catch (e) {
      setError(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  function makeUniqueNodeId(base: string) {
    const raw = String(base || '').trim() || 'node'
    const cleaned = raw.replace(/[<>:"/\\|?*]/g, '_').trim() || 'node'
    const hasId = (id: string) => nodes.value.some((node) => node.id === id)
    if (!hasId(cleaned)) return cleaned
    for (let index = 1; index < 10000; index += 1) {
      const candidate = `${cleaned}${index}`
      if (!hasId(candidate)) return candidate
    }
    return `${cleaned}_${Date.now()}`
  }

  function graphNodeForMobileNode(node: MobileNode, nodeId: string, ui: { x: number; y: number }) {
    const graphNode = (graphConfig.value?.nodes || []).find((item) => item.id === node.id)
    return {
      id: nodeId,
      typeId: String(node.type_id || graphNode?.typeId || '').trim(),
      name: nodeId,
      input_num: Number(node.input_num || graphNode?.input_num || 1),
      output_num: Number(node.output_num || graphNode?.output_num || 1),
      ui,
      providerId: String(graphNode?.providerId ?? '').trim(),
      mode: String(graphNode?.mode ?? '').trim(),
      web_search: graphNode?.web_search,
      thinking: graphNode?.thinking,
      reasoning_effort: String(graphNode?.reasoning_effort ?? ''),
      instruction: String(graphNode?.instruction ?? ''),
      systemPrompt: String(graphNode?.systemPrompt ?? ''),
      plugins: Array.isArray(graphNode?.plugins) ? graphNode.plugins.map(String).filter(Boolean) : [],
      tools: Array.isArray(graphNode?.tools) ? graphNode.tools.map(String).filter(Boolean) : [],
      mcpServers: Array.isArray(graphNode?.mcpServers) ? graphNode.mcpServers.map(String).filter(Boolean) : [],
      workingPath: String(graphNode?.workingPath ?? '').trim(),
    }
  }

  function nextMobileNodeUi() {
    const index = nodes.value.length
    return {
      x: 80 + (index % 3) * 260,
      y: 80 + Math.floor(index / 3) * 180,
    }
  }

  async function persistGraphNodeList(graphId: string, mutate: (graph: GraphConfig) => GraphConfig) {
    const graph = await loadGraph(graphId)
    const next = mutate({
      ...graph,
      nodes: Array.isArray(graph.nodes) ? graph.nodes : [],
      output_routes: graph.output_routes && typeof graph.output_routes === 'object' ? graph.output_routes : {},
    })
    await saveGraph(graphId, next, { saveReason: 'mobile_node_list_change' })
    graphConfig.value = normalizeGraphConfig(next)
  }

  async function createNode(typeId: string, nodeName: string, fields: Record<string, unknown>) {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const safeTypeId = String(typeId || '').trim()
    if (!graphId || !safeTypeId) throw new Error('Graph and node type are required')
    const requestedName = String(nodeName || safeTypeId).trim() || safeTypeId
    const nodeId = makeUniqueNodeId(requestedName)
    const ui = nextMobileNodeUi()
    error.value = ''
    loading.value = true
    try {
      const created = await createNodeInstance(nodeId, safeTypeId, nodeId, graphId, ui)
      const createdNodeId = String(created?.node_id || nodeId).trim() || nodeId
      if (fields && Object.keys(fields).length) {
        await updateNodeInstanceConfig(createdNodeId, { fields }, graphId)
      }
      const typeInfo = availableNodeTypes.value.find((item) => item.id === safeTypeId)
      await persistGraphNodeList(graphId, (graph) => ({
        ...graph,
        nodes: [
          ...(graph.nodes || []).filter((node) => node.id !== createdNodeId),
          {
            id: createdNodeId,
            typeId: safeTypeId,
            name: createdNodeId,
            input_num: Number(typeInfo?.input_num || 1),
            output_num: Number(typeInfo?.output_num || 1),
            ui,
            providerId: String((fields as any)?.provider_id ?? '').trim(),
            mode: String((fields as any)?.mode ?? '').trim(),
            web_search: (fields as any)?.web_search as any,
            thinking: (fields as any)?.thinking as any,
            reasoning_effort: String((fields as any)?.reasoning_effort ?? ''),
            instruction: String((fields as any)?.instruction ?? ''),
            systemPrompt: String((fields as any)?.system_prompt ?? ''),
            plugins: Array.isArray((fields as any)?.plugins) ? (fields as any).plugins.map(String).filter(Boolean) : [],
            tools: Array.isArray((fields as any)?.tools) ? (fields as any).tools.map(String).filter(Boolean) : [],
            mcpServers: Array.isArray((fields as any)?.mcp_servers) ? (fields as any).mcp_servers.map(String).filter(Boolean) : [],
            workingPath: String((fields as any)?.working_path ?? '').trim(),
          },
        ],
      }))
      logMobileGraphEvent('node_created', {
        node_id: createdNodeId,
        node_instance_id: createdNodeId,
        node_type_id: safeTypeId,
      })
      await refreshNodes()
      return createdNodeId
    } catch (e) {
      setError(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function createNodeFromProfile(profileId: string) {
    const safeProfileId = String(profileId || '').trim()
    if (!safeProfileId) throw new Error('Node preset is required')
    const profile = agentProfiles.value.find((item) => item.id === safeProfileId)
    if (!profile) throw new Error(`Node preset not found: ${safeProfileId}`)
    const nodeTypeId = String(profile.node_type_id || '').trim()
    if (!nodeTypeId) throw new Error(`Node preset "${safeProfileId}" is missing node_type_id`)
    const nodeName = String(profile.node_name || profile.name || profile.id || nodeTypeId).trim() || nodeTypeId
    return createNode(nodeTypeId, nodeName, { ...(profile.fields || {}) })
  }

  async function deleteNode(node: MobileNode) {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(node?.id || '').trim()
    if (!graphId || !nodeId) throw new Error('Graph and Node selection are required')
    error.value = ''
    loading.value = true
    try {
      await deleteNodeInstance(nodeId, graphId)
      await persistGraphNodeList(graphId, (graph) => ({
        ...graph,
        nodes: (graph.nodes || []).filter((item) => item.id !== nodeId),
        output_routes: pruneOutputRoutesForNode(graph.output_routes || {}, nodeId),
      }))
      logMobileGraphEvent('node_deleted', {
        node_id: nodeId,
        node_instance_id: nodeId,
        node_type_id: node.type_id,
      })
      if (selectedNode.value?.id === nodeId) {
        selectedNode.value = null
        conversation.value = null
      }
      await refreshNodes()
    } catch (e) {
      setError(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function triggerNode(node: MobileNode) {
    const selection = requireGraphSelection()
    const graphId = selection.graphId
    const nodeId = String(node?.id || '').trim()
    if (!graphId || !nodeId) throw new Error('Graph and Node selection are required')
    error.value = ''
    try {
      const input = String(nodeTriggerInputs.value[nodeId] || '')
      const prevRunAt = String(node.last_run_at ?? '')
      const prevMessage = String(node.last_message ?? '')
      await startGraphRunner(graphId).catch(() => null)
      await emitGraph(graphId, nodeId, input).catch(() => null)
      scheduleGraphRefresh(selectedNode.value?.id === nodeId)
      const waited = await waitForNodeOutputFromSummary(selection, nodeId, prevRunAt || null, prevMessage || null)
      if (waited.status === 'completed') {
        const current = nodes.value.find((item) => item.id === nodeId)
        if (current) current.last_message = waited.message
        if (selectedNode.value?.id === nodeId) {
          selectedNode.value = { ...selectedNode.value, last_message: waited.message }
        }
      }
      const tasks: Promise<unknown>[] = [refreshNodes(), refreshGraphConfig()]
      if (selectedNode.value?.id === nodeId) tasks.push(refreshConversation())
      await Promise.all(tasks)
    } catch (e) {
      setError(e)
      throw e
    }
  }

  async function copyNode(node: MobileNode) {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const sourceNodeId = String(node?.id || '').trim()
    if (!graphId || !sourceNodeId) throw new Error('Graph and Node selection are required')
    const newNodeId = makeUniqueNodeId(`${String(node.name || sourceNodeId).trim() || 'node'}1`)
    const ui = nextMobileNodeUi()
    error.value = ''
    loading.value = true
    try {
      const cloned = await cloneNodeInstance(sourceNodeId, graphId, newNodeId, newNodeId, ui, graphId)
      const clonedNodeId = String(cloned?.node_id || newNodeId).trim() || newNodeId
      await persistGraphNodeList(graphId, (graph) => ({
        ...graph,
        nodes: [
          ...(graph.nodes || []).filter((item) => item.id !== clonedNodeId),
          graphNodeForMobileNode(node, clonedNodeId, ui),
        ],
      }))
      logMobileGraphEvent('node_cloned', {
        source_node_id: sourceNodeId,
        node_id: clonedNodeId,
        node_instance_id: clonedNodeId,
        node_type_id: node.type_id,
      })
      await Promise.all([refreshNodes(), refreshGraphConfig()])
      return clonedNodeId
    } catch (e) {
      setError(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function setSelectedNodeFields(fields: Record<string, unknown>, options: { emitEvent?: boolean } = {}) {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!graphId || !nodeId) throw new Error('Graph and Node selection are required')
    const result = await updateNodeInstanceConfig(nodeId, { fields }, graphId)
    if (result?.after && typeof result.after === 'object') {
      mergeNodeConfig(nodeId, result.after)
    }
    const summaryPatch: Partial<MobileNode> = {}
    if (Object.prototype.hasOwnProperty.call(fields, 'goal')) summaryPatch.goal = String(fields.goal || '')
    if (Object.prototype.hasOwnProperty.call(fields, 'goal_state')) {
      summaryPatch.goal_state = fields.goal_state && typeof fields.goal_state === 'object'
        ? (fields.goal_state as Record<string, unknown>)
        : null
    }
    if (Object.keys(summaryPatch).length) mergeMobileNodeSummary(nodeId, summaryPatch)
    if (options.emitEvent !== false) {
      logMobileGraphEvent('node_config_updated', {
        node_id: nodeId,
        node_instance_id: nodeId,
        changed_fields: Object.keys(fields || {}),
      })
    }
  }

  async function clearSelectedNodeFields(fields: string[]) {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!graphId || !nodeId) throw new Error('Graph and Node selection are required')
    await updateNodeInstanceConfig(nodeId, { clear_fields: fields }, graphId)
    const existing = nodeConfigs.value[nodeId]
    if (existing) {
      const next = { ...existing }
      for (const field of fields) delete (next as any)[field]
      nodeConfigs.value = { ...nodeConfigs.value, [nodeId]: next }
    }
    const summaryPatch: Partial<MobileNode> = {}
    if (fields.includes('goal')) summaryPatch.goal = ''
    if (fields.includes('goal_state')) summaryPatch.goal_state = null
    if (Object.keys(summaryPatch).length) mergeMobileNodeSummary(nodeId, summaryPatch)
    logMobileGraphEvent('node_config_updated', {
      node_id: nodeId,
      node_instance_id: nodeId,
      cleared_fields: fields,
    })
  }

  async function renameSelectedNode(name: string) {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    const nextName = String(name || '').trim()
    if (!graphId || !nodeId) throw new Error('Graph and Node selection are required')
    if (!nextName) throw new Error('Node name is required')
    const currentName = String(selectedNode.value?.name || nodeId).trim()
    if (nextName === currentName) return
    await renameNodeInstance(nodeId, graphId, nodeId, nextName)
    await Promise.all([refreshNodes(), refreshGraphConfig()])
  }

  async function selectGraph(graph: MobileGraph) {
    const graphId = String(graph.id || '').trim()
    if (!graphId) throw new Error('Graph id is required')
    selectedGraph.value = graph
    selectedNode.value = null
    nodeConfigs.value = {}
    conversation.value = null
    view.value = 'nodes'
    error.value = ''
    loading.value = true
    try {
      await Promise.all([loadEditorCatalog(), refreshNodes(), refreshGraphConfig()])
      startGraphEventStream()
    } catch (e) {
      setError(e)
    } finally {
      loading.value = false
    }
  }

  async function refreshConversation() {
    await refreshConversationForSelection(requireChatSelection())
  }

  function setConversationLiveMessage(text: string) {
    if (!conversation.value) return
    conversation.value = {
      ...conversation.value,
      live_message: text,
    }
  }

  function setConversationThinkingMessage(text: string) {
    if (!conversation.value) return
    conversation.value = {
      ...conversation.value,
      thinking_message: text,
    }
  }

  async function selectNode(node: MobileNode) {
    const nodeId = String(node.id || '').trim()
    if (!nodeId) throw new Error('Node id is required')
    stopGraphEventStream()
    selectedNode.value = node
    view.value = 'chat'
    error.value = ''
    clearConversationCommit()
    loading.value = true
    try {
      await refreshConversation()
      startChatStreams()
    } catch (e) {
      setError(e)
    } finally {
      loading.value = false
    }
  }

  async function sendMessage(message: string | MessageEnvelope) {
    const selection = requireChatSelection()
    sending.value = true
    error.value = ''
    try {
      const response = await sendMobileNodeMessage(selection.pcId, selection.graphId, selection.nodeId, message)
      applySentMessageSnapshot(selection, response)
      return response
    } catch (e) {
      setError(e)
      throw e
    } finally {
      sending.value = false
    }
  }

  function markSelectedNodeStopRequested(nodeId: string) {
    const nextNodes = nodes.value.map((node) => {
      if (node.id !== nodeId) return node
      return {
        ...node,
        state: 'working' as const,
        has_inflight: true,
        stop_requested: true,
        last_message: 'Stop requested. Cancelling active work.',
      }
    })
    nodes.value = nextNodes
    if (selectedNode.value?.id === nodeId) {
      selectedNode.value = nextNodes.find((node) => node.id === nodeId) || selectedNode.value
    }
  }

  async function stopSelectedNodeWork() {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!graphId || !nodeId) throw new Error('Graph and Node selection are required')
    error.value = ''
    markSelectedNodeStopRequested(nodeId)
    try {
      const response = await controlNodeInstance(nodeId, 'stop', graphId)
      const nextNodes = nodes.value.map((node) => {
        if (node.id !== nodeId) return node
        return { ...node, state: response.state, has_inflight: false, stop_requested: false }
      })
      nodes.value = nextNodes
      if (selectedNode.value?.id === nodeId) {
        selectedNode.value = nextNodes.find((node) => node.id === nodeId) || selectedNode.value
      }
      await Promise.all([refreshNodes(), refreshConversation()])
    } catch (e) {
      setError(e)
      await Promise.allSettled([refreshNodes(), refreshConversation()])
      throw e
    }
  }

  async function clearSelectedNodeMemory() {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!graphId || !nodeId) throw new Error('Graph and Node selection are required')
    error.value = ''
    loading.value = true
    try {
      await clearNodeInstanceMemory(nodeId, graphId)
      conversation.value = null
      logMobileGraphEvent('node_memory_cleared', {
        node_id: nodeId,
        node_instance_id: nodeId,
      })
      await Promise.all([refreshNodes(), refreshConversation()])
    } catch (e) {
      setError(e)
    } finally {
      loading.value = false
    }
  }

  async function deleteSelectedNodeMessage(messageId: string) {
    const pcId = String(selectedPc.value?.id || '').trim()
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    const safeMessageId = String(messageId || '').trim()
    if (!pcId || !graphId || !nodeId || !safeMessageId) throw new Error('PC, Graph, Node, and Message selection are required')
    error.value = ''
    try {
      await deleteMobileNodeMessage(pcId, graphId, nodeId, safeMessageId)
      if (conversation.value?.messages) {
        conversation.value = {
          ...conversation.value,
          messages: conversation.value.messages.filter((item) => String((item as any)?.id || '') !== safeMessageId),
        }
      }
      await refreshConversation()
    } catch (e) {
      setError(e)
      throw e
    }
  }

  function outputRoutesForNode(sourceNodeId: string) {
    return flattenOutputRoutes(graphConfig.value?.output_routes || {}, sourceNodeId)
  }

  async function persistOutputRoutes(nextRoutes: GraphOutputRoutes, saveReason: string) {
    const graphId = String(selectedGraph.value?.id || '').trim()
    if (!graphId) throw new Error('Graph selection is required')
    const graph = graphConfig.value || normalizeGraphConfig(await loadGraph(graphId))
    const next = normalizeGraphConfig({
      ...graph,
      output_routes: nextRoutes,
    })
    await saveGraph(graphId, next, { saveReason })
    graphConfig.value = next
    logMobileGraphEvent('graph_save_api', {
      reason: saveReason,
      output_routes_count: Object.keys(next.output_routes || {}).length,
    })
  }

  async function addSelectedNodeOutputRoute() {
    const sourceNodeId = String(selectedNode.value?.id || '').trim()
    if (!sourceNodeId) throw new Error('Node selection is required')
    if (!graphConfig.value) await refreshGraphConfig()
    const targetNodes = nodes.value.filter((node) => node.id !== sourceNodeId)
    if (!targetNodes.length) throw new Error('Create another node before adding an output route.')

    const outputCount = portCount(selectedNode.value?.output_num, 1)
    const existing = outputRoutesForNode(sourceNodeId)
    const existingKeys = new Set(existing.map(routeKey))
    for (let outputIndex = 0; outputIndex < outputCount; outputIndex += 1) {
      for (const targetNode of targetNodes) {
        const targetNodeId = String(targetNode.id || '').trim()
        if (!targetNodeId) continue
        const inputCount = portCount(targetNode.input_num, 1)
        for (let inputIndex = 0; inputIndex < inputCount; inputIndex += 1) {
          const candidate = { outputIndex, targetNodeId, inputIndex }
          if (existingKeys.has(routeKey(candidate))) continue
          const nextRoutes = buildOutputRoutes(sourceNodeId, [
            ...existing,
            { id: '', ...candidate },
          ], graphConfig.value?.output_routes || {})
          await persistOutputRoutes(nextRoutes, 'mobile_add_output_route')
          return
        }
      }
    }
    throw new Error('All available output routes already exist.')
  }

  async function updateSelectedNodeOutputRoute(
    routeId: string,
    patch: { outputIndex?: number; targetNodeId?: string; inputIndex?: number },
  ) {
    const sourceNodeId = String(selectedNode.value?.id || '').trim()
    if (!sourceNodeId) throw new Error('Node selection is required')
    if (!graphConfig.value) await refreshGraphConfig()
    const rows = outputRoutesForNode(sourceNodeId)
    const index = rows.findIndex((row) => row.id === routeId)
    const existing = rows[index]
    if (index < 0 || !existing) return
    const nextRow: MobileOutputRouteRow = {
      ...existing,
      outputIndex: patch.outputIndex == null ? existing.outputIndex : portIndex(patch.outputIndex, 0),
      targetNodeId: patch.targetNodeId == null ? existing.targetNodeId : String(patch.targetNodeId || '').trim(),
      inputIndex: patch.inputIndex == null ? existing.inputIndex : portIndex(patch.inputIndex, 0),
    }
    if (!nextRow.targetNodeId || nextRow.targetNodeId === sourceNodeId) return
    const duplicate = rows.some((row) => row.id !== routeId && routeKey(row) === routeKey(nextRow))
    if (duplicate) throw new Error('Output route already exists.')
    rows.splice(index, 1, nextRow)
    const nextRoutes = buildOutputRoutes(sourceNodeId, rows, graphConfig.value?.output_routes || {})
    await persistOutputRoutes(nextRoutes, 'mobile_update_output_route')
  }

  async function removeSelectedNodeOutputRoute(routeId: string) {
    const sourceNodeId = String(selectedNode.value?.id || '').trim()
    if (!sourceNodeId) throw new Error('Node selection is required')
    if (!graphConfig.value) await refreshGraphConfig()
    const rows = outputRoutesForNode(sourceNodeId).filter((row) => row.id !== routeId)
    const nextRoutes = buildOutputRoutes(sourceNodeId, rows, graphConfig.value?.output_routes || {})
    await persistOutputRoutes(nextRoutes, 'mobile_remove_output_route')
  }

  async function refreshCurrent() {
    if (view.value === 'pcs') {
      await loadPcs()
      return
    }
    if (view.value === 'graphs') {
      const pc = selectedPc.value
      if (!pc) throw new Error('PC selection is required')
      graphInstances.value = await listMobileGraphs(pc.id)
      return
    }
    if (view.value === 'nodes') {
      await Promise.all([refreshNodes(), refreshGraphConfig()])
      return
    }
    await Promise.all([refreshNodes(), refreshGraphConfig(), refreshConversation()])
  }

  function backToPcs() {
    void loadPcs()
  }

  function backToGraphs() {
    stopPolling()
    selectedGraph.value = null
    selectedNode.value = null
    nodes.value = []
    graphConfig.value = null
    nodeConfigs.value = {}
    conversation.value = null
    view.value = 'graphs'
  }

  function backToNodes() {
    stopChatStreams()
    selectedNode.value = null
    conversation.value = null
    view.value = 'nodes'
    startGraphEventStream()
  }

  function graphEventTargetsSelectedNode(payload: Record<string, unknown>, nodeId: string) {
    const target = String(nodeId || '').trim()
    if (!target) return false
    const candidates = [
      payload.node_instance_id,
      payload.node_id,
      payload.from_id,
      payload.from_node,
      payload.to_node,
      payload.source_node_id,
      payload.new_node_id,
      payload.old_node_id,
    ]
    if (candidates.some((item) => String(item || '').trim() === target)) return true
    const foldedTarget = target.toLowerCase()
    return candidates.some((item) => String(item || '').trim().toLowerCase() === foldedTarget)
  }

  function logMobileGraphEvent(event: string, payload: Record<string, unknown> = {}) {
    handleGraphEventPayload({
      ...payload,
      event,
      graph_id: String(selectedGraph.value?.id || '').trim(),
    })
  }

  function handleGraphEventPayload(payload: Record<string, unknown>) {
    const eventName = String(payload?.event || '').trim()
    if (!chatNodeRefreshGraphEvents.has(eventName)) return
    if (view.value === 'nodes') {
      scheduleGraphRefresh({
        includeConversation: false,
        includeGraphConfig: !chatLightweightGraphEvents.has(eventName),
      })
      return
    }
    if (view.value !== 'chat') return
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!graphEventTargetsSelectedNode(payload, nodeId)) return
    const includeConversation = chatConversationGraphEvents.has(eventName)
    scheduleGraphRefresh({ includeConversation, includeGraphConfig: !chatLightweightGraphEvents.has(eventName) })
  }

  function scheduleGraphRefresh(options: boolean | { includeConversation?: boolean; includeGraphConfig?: boolean }) {
    const includeConversation = typeof options === 'boolean' ? options : !!options.includeConversation
    const includeGraphConfig = typeof options === 'boolean' ? true : options.includeGraphConfig !== false
    graphRefreshNeedsConversation = graphRefreshNeedsConversation || includeConversation
    graphRefreshNeedsGraphConfig = graphRefreshNeedsGraphConfig || includeGraphConfig
    if (graphRefreshTimer != null) return
    graphRefreshTimer = window.setTimeout(async () => {
      graphRefreshTimer = null
      if (graphRefreshInFlight) {
        scheduleGraphRefresh({
          includeConversation: graphRefreshNeedsConversation,
          includeGraphConfig: graphRefreshNeedsGraphConfig,
        })
        return
      }
      if (view.value !== 'nodes' && view.value !== 'chat') return
      graphRefreshInFlight = true
      const shouldRefreshConversation = graphRefreshNeedsConversation && view.value === 'chat'
      const shouldRefreshGraphConfig = graphRefreshNeedsGraphConfig
      graphRefreshNeedsConversation = false
      graphRefreshNeedsGraphConfig = false
      try {
        const tasks: Promise<unknown>[] = [refreshNodes()]
        if (shouldRefreshGraphConfig) tasks.push(refreshGraphConfig())
        if (shouldRefreshConversation) tasks.push(refreshConversation())
        await Promise.all(tasks)
      } catch (e) {
        setError(e)
      } finally {
        graphRefreshInFlight = false
      }
    }, 75)
  }

  function startChatLiveStream() {
    const pcId = String(selectedPc.value?.id || '').trim()
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!pcId || !graphId || !nodeId) {
      stopChatLiveStream()
      return
    }
    const streamKey = `${pcId}:${graphId}:${nodeId}`
    if (chatLiveEventSource && chatLiveStreamKey === streamKey) return
    stopChatLiveStream()

    const source = new EventSource(nodeInstanceLiveStreamUrl(nodeId, graphId))
    chatLiveEventSource = source
    chatLiveStreamKey = streamKey
    source.onmessage = (event) => {
      if (chatLiveEventSource !== source) return
      if (view.value !== 'chat') return
      if (String(selectedPc.value?.id || '').trim() !== pcId) return
      if (String(selectedGraph.value?.id || '').trim() !== graphId) return
      if (String(selectedNode.value?.id || '').trim() !== nodeId) return
      try {
        const payload = JSON.parse(String(event.data || '{}'))
        const eventType = String(payload?.event_type || payload?.event?.type || '').trim()
        const eventData = payload?.event && typeof payload.event === 'object'
          ? (payload.event as Record<string, unknown>)
          : null
        const nextLiveMessage = String(payload?.live_message || '')
        const nextThinkingMessage = String(payload?.thinking_message || '')
        setConversationThinkingMessage(nextThinkingMessage)
        if (eventType === 'node_message_done' || eventType === 'node_output') {
          rememberConversationCommit(
            String(eventData?.text || nextLiveMessage || conversation.value?.live_message || ''),
            String(payload?.trace_id || eventData?.trace_id || ''),
          )
          if (pendingConversationLiveText) setConversationLiveMessage(pendingConversationLiveText)
          setConversationThinkingMessage('')
        } else if (nextLiveMessage || !pendingConversationLiveText) {
          setConversationLiveMessage(nextLiveMessage)
        }
        if (chatConversationRefreshEvents.has(eventType)) {
          scheduleGraphRefresh({ includeConversation: true, includeGraphConfig: false })
        }
      } catch {
        // Ignore malformed stream payloads; the next valid event will correct the chat view.
      }
    }
    source.onerror = () => {
      if (chatLiveEventSource !== source) return
      if (
        view.value !== 'chat' ||
        String(selectedPc.value?.id || '').trim() !== pcId ||
        String(selectedGraph.value?.id || '').trim() !== graphId ||
        String(selectedNode.value?.id || '').trim() !== nodeId
      ) {
        source.close()
        chatLiveEventSource = null
        chatLiveStreamKey = ''
      }
    }
  }

  function stopChatLiveStream() {
    if (chatLiveEventSource) {
      chatLiveEventSource.close()
      chatLiveEventSource = null
    }
    chatLiveStreamKey = ''
  }

  function startGraphEventStream() {
    const pcId = String(selectedPc.value?.id || '').trim()
    const graphId = String(selectedGraph.value?.id || '').trim()
    if (!pcId || !graphId) {
      stopGraphEventStream()
      return
    }
    const streamKey = `${pcId}:${graphId}`
    if (graphEventSource && graphEventStreamKey === streamKey) return
    stopGraphEventStream()

    const source = new EventSource(graphEventsStreamUrl(graphId))
    graphEventSource = source
    graphEventStreamKey = streamKey
    source.onmessage = (event) => {
      if (graphEventSource !== source) return
      if (view.value !== 'nodes' && view.value !== 'chat') return
      if (String(selectedPc.value?.id || '').trim() !== pcId) return
      if (String(selectedGraph.value?.id || '').trim() !== graphId) return
      try {
        const payload = JSON.parse(String(event.data || '{}')) as Record<string, unknown>
        handleGraphEventPayload(payload)
      } catch {
        // Ignore malformed graph events; EventSource will keep delivering later updates.
      }
    }
    source.onerror = () => {
      if (graphEventSource !== source) return
      if (
        (view.value !== 'nodes' && view.value !== 'chat') ||
        String(selectedPc.value?.id || '').trim() !== pcId ||
        String(selectedGraph.value?.id || '').trim() !== graphId
      ) {
        source.close()
        graphEventSource = null
        graphEventStreamKey = ''
      }
    }
  }

  function startChatStreams() {
    stopChatLiveStream()
    startChatLiveStream()
  }

  function stopChatStreams() {
    stopChatLiveStream()
  }

  function stopGraphEventStream() {
    if (graphEventSource) {
      graphEventSource.close()
      graphEventSource = null
    }
    graphEventStreamKey = ''
    if (graphRefreshTimer != null) {
      window.clearTimeout(graphRefreshTimer)
      graphRefreshTimer = null
    }
    graphRefreshInFlight = false
    graphRefreshNeedsConversation = false
    graphRefreshNeedsGraphConfig = false
  }

  function stopPolling() {
    stopChatStreams()
    stopGraphEventStream()
  }

  onBeforeUnmount(stopPolling)

  return {
    view,
    pcs,
    graphInstances,
    flatGraphs,
    nodes,
    graphConfig,
    availableNodeTypes,
    agentProfiles,
    graphProfiles,
    providers,
    availableTools,
    conversation,
    selectedPc,
    selectedGraph,
    selectedNode,
    selectedConfig,
    selectedNodeOutputRoutes,
    loading,
    sending,
    error,
    loadPcs,
    selectPc,
    selectGraph,
    selectNode,
    sendMessage,
    stopSelectedNodeWork,
    setSelectedNodeFields,
    clearSelectedNodeFields,
    renameSelectedNode,
    clearSelectedNodeMemory,
    deleteSelectedNodeMessage,
    refreshGraphConfig,
    addSelectedNodeOutputRoute,
    updateSelectedNodeOutputRoute,
    removeSelectedNodeOutputRoute,
    saveGraphByName,
    deleteGraphById,
    createGraphFromPreset,
    createNode,
    createNodeFromProfile,
    deleteNode,
    triggerNode,
    copyNode,
    refreshCurrent,
    refreshSelectedNodeConfig,
    refreshEditorCatalog,
    refreshAgentProfiles,
    refreshGraphProfiles,
    backToPcs,
    backToGraphs,
    backToNodes,
  }
}
