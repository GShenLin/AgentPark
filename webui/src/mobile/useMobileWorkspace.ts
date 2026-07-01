import { computed, onBeforeUnmount, ref } from 'vue'
import {
  clearNodeInstanceMemory,
  controlNodeInstance,
  createNodeInstance,
  deleteGraph,
  deleteMobileNodeMessage,
  deleteNodeInstance,
  getMobileNodeConversation,
  graphEventsStreamUrl,
  listNodes,
  listNodeInstanceConfigs,
  listMobileGraphs,
  listMobileNodes,
  listMobilePcs,
  listProviders,
  listTools,
  loadGraph,
  nodeInstanceLiveStreamUrl,
  saveGraph,
  sendMobileNodeMessage,
  setStartupGraphConfig,
  updateNodeInstanceConfig,
  type GraphConfig,
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

export type MobileView = 'pcs' | 'graphs' | 'nodes' | 'chat'

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

export function useMobileWorkspace() {
  const view = ref<MobileView>('pcs')
  const pcs = ref<MobilePc[]>([])
  const graphInstances = ref<MobileGraphInstance[]>([])
  const nodes = ref<MobileNode[]>([])
  const nodeConfigs = ref<Record<string, NodeInstanceConfig>>({})
  const availableNodeTypes = ref<NodeInfo[]>([])
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

  const flatGraphs = computed(() => graphInstances.value.flatMap((item) => item.graphs))
  const selectedConfig = computed(() => {
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!nodeId) return null
    return nodeConfigs.value[nodeId] || null
  })

  let loadRequestId = 0

  function setError(value: unknown) {
    error.value = String((value as { message?: unknown })?.message || value || '')
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

  async function selectPc(pc: MobilePc) {
    const requestId = ++loadRequestId
    const pcId = String(pc.id || '').trim()
    if (!pcId) throw new Error('PC id is required')
    stopPolling()
    selectedPc.value = pc
    selectedGraph.value = null
    selectedNode.value = null
    nodes.value = []
    conversation.value = null
    view.value = 'graphs'
    error.value = ''
    loading.value = true
    try {
      const nextGraphInstances = await listMobileGraphs(pcId)
      if (requestId !== loadRequestId) return
      graphInstances.value = nextGraphInstances
    } catch (e) {
      if (requestId !== loadRequestId) return
      setError(e)
    } finally {
      if (requestId === loadRequestId) loading.value = false
    }
  }

  async function refreshNodes() {
    const pcId = String(selectedPc.value?.id || '').trim()
    const graphId = String(selectedGraph.value?.id || '').trim()
    if (!pcId || !graphId) throw new Error('PC and Graph selection are required')
    nodes.value = await listMobileNodes(pcId, graphId)
    if (selectedNode.value) {
      const current = nodes.value.find((item) => item.id === selectedNode.value?.id)
      if (current) selectedNode.value = current
    }
  }

  async function refreshNodeConfigs() {
    const graphId = String(selectedGraph.value?.id || '').trim()
    if (!graphId) throw new Error('Graph selection is required')
    const response = await listNodeInstanceConfigs(graphId)
    const configs = response.nodes || []
    const next: Record<string, NodeInstanceConfig> = {}
    for (const item of configs) {
      const nodeId = String(item.node_id || '').trim()
      if (nodeId) next[nodeId] = item
    }
    nodeConfigs.value = next
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
        links: [],
      }
      const result = await saveGraph(graphName, payload, { saveReason: 'mobile_save_graph' })
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
      links: Array.isArray(graph.links) ? graph.links : [],
    })
    await saveGraph(graphId, next, { saveReason: 'mobile_node_list_change' })
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
      await Promise.all([refreshNodes(), refreshNodeConfigs()])
      return createdNodeId
    } catch (e) {
      setError(e)
      throw e
    } finally {
      loading.value = false
    }
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
        links: (graph.links || []).filter((link) => link.from?.node !== nodeId && link.to?.node !== nodeId),
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
      await Promise.all([refreshNodes(), refreshNodeConfigs()])
    } catch (e) {
      setError(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function setSelectedNodeFields(fields: Record<string, unknown>) {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!graphId || !nodeId) throw new Error('Graph and Node selection are required')
    await updateNodeInstanceConfig(nodeId, { fields }, graphId)
    logMobileGraphEvent('node_config_updated', {
      node_id: nodeId,
      node_instance_id: nodeId,
      changed_fields: Object.keys(fields || {}),
    })
    await refreshNodeConfigs()
  }

  async function clearSelectedNodeFields(fields: string[]) {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!graphId || !nodeId) throw new Error('Graph and Node selection are required')
    await updateNodeInstanceConfig(nodeId, { clear_fields: fields }, graphId)
    logMobileGraphEvent('node_config_updated', {
      node_id: nodeId,
      node_instance_id: nodeId,
      cleared_fields: fields,
    })
    await refreshNodeConfigs()
  }

  async function selectGraph(graph: MobileGraph) {
    const graphId = String(graph.id || '').trim()
    if (!graphId) throw new Error('Graph id is required')
    selectedGraph.value = graph
    selectedNode.value = null
    conversation.value = null
    view.value = 'nodes'
    error.value = ''
    loading.value = true
    try {
      await Promise.all([loadEditorCatalog(), refreshNodes(), refreshNodeConfigs()])
      startGraphEventStream()
    } catch (e) {
      setError(e)
    } finally {
      loading.value = false
    }
  }

  async function refreshConversation() {
    const pcId = String(selectedPc.value?.id || '').trim()
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!pcId || !graphId || !nodeId) throw new Error('PC, Graph, and Node selection are required')
    conversation.value = await getMobileNodeConversation(pcId, graphId, nodeId)
  }

  function setConversationLiveMessage(text: string) {
    if (!conversation.value) return
    conversation.value = {
      ...conversation.value,
      live_message: text,
    }
  }

  async function selectNode(node: MobileNode) {
    const nodeId = String(node.id || '').trim()
    if (!nodeId) throw new Error('Node id is required')
    selectedNode.value = node
    view.value = 'chat'
    error.value = ''
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
    const pcId = String(selectedPc.value?.id || '').trim()
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!pcId || !graphId || !nodeId) throw new Error('PC, Graph, and Node selection are required')
    sending.value = true
    error.value = ''
    try {
      await sendMobileNodeMessage(pcId, graphId, nodeId, message)
      await Promise.all([refreshNodes(), refreshConversation()])
    } catch (e) {
      setError(e)
    } finally {
      sending.value = false
    }
  }

  function markSelectedNodeStopRequested(nodeId: string) {
    const cfg = nodeConfigs.value[nodeId]
    nodeConfigs.value = {
      ...nodeConfigs.value,
      [nodeId]: {
        ...(cfg || ({ node_id: nodeId, type_id: '' } as NodeInstanceConfig)),
        node_id: nodeId,
        _stop_requested: true,
        state: 'working',
        last_message: 'Stop requested. Cancelling active work.',
      } as NodeInstanceConfig,
    }
    const nextNodes = nodes.value.map((node) => {
      if (node.id !== nodeId) return node
      return {
        ...node,
        state: 'working' as const,
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
      const cfg = nodeConfigs.value[nodeId]
      if (cfg) {
        nodeConfigs.value = {
          ...nodeConfigs.value,
          [nodeId]: {
            ...cfg,
            state: response.state,
          },
        }
      }
      await Promise.all([refreshNodes(), refreshNodeConfigs(), refreshConversation()])
    } catch (e) {
      setError(e)
      await Promise.allSettled([refreshNodes(), refreshNodeConfigs(), refreshConversation()])
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
      await Promise.all([refreshNodes(), refreshNodeConfigs()])
      return
    }
    await Promise.all([refreshNodes(), refreshNodeConfigs(), refreshConversation()])
  }

  function backToPcs() {
    void loadPcs()
  }

  function backToGraphs() {
    stopPolling()
    selectedGraph.value = null
    selectedNode.value = null
    nodes.value = []
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
    return candidates.some((item) => String(item || '').trim() === target)
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
      scheduleGraphRefresh(false)
      return
    }
    if (view.value !== 'chat') return
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!graphEventTargetsSelectedNode(payload, nodeId)) return
    scheduleGraphRefresh(chatConversationGraphEvents.has(eventName))
  }

  function scheduleGraphRefresh(includeConversation: boolean) {
    graphRefreshNeedsConversation = graphRefreshNeedsConversation || includeConversation
    if (graphRefreshTimer != null) return
    graphRefreshTimer = window.setTimeout(async () => {
      graphRefreshTimer = null
      if (graphRefreshInFlight) {
        scheduleGraphRefresh(false)
        return
      }
      if (view.value !== 'nodes' && view.value !== 'chat') return
      graphRefreshInFlight = true
      const shouldRefreshConversation = graphRefreshNeedsConversation && view.value === 'chat'
      graphRefreshNeedsConversation = false
      try {
        const tasks: Promise<unknown>[] = [refreshNodes(), refreshNodeConfigs()]
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
        setConversationLiveMessage(String(payload?.live_message || ''))
        const eventType = String(payload?.event_type || payload?.event?.type || '').trim()
        if (chatConversationRefreshEvents.has(eventType)) {
          scheduleGraphRefresh(true)
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
    startGraphEventStream()
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
    nodeConfigs,
    availableNodeTypes,
    providers,
    availableTools,
    conversation,
    selectedPc,
    selectedGraph,
    selectedNode,
    selectedConfig,
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
    clearSelectedNodeMemory,
    deleteSelectedNodeMessage,
    saveGraphByName,
    deleteGraphById,
    createNode,
    deleteNode,
    refreshCurrent,
    refreshNodeConfigs,
    refreshEditorCatalog,
    backToPcs,
    backToGraphs,
    backToNodes,
  }
}
