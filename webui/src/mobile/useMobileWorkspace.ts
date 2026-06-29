import { computed, onBeforeUnmount, ref } from 'vue'
import {
  clearNodeInstanceMemory,
  createNodeInstance,
  deleteGraph,
  deleteMobileNodeMessage,
  deleteNodeInstance,
  getMobileNodeConversation,
  listNodes,
  listNodeInstanceConfigs,
  listMobileGraphs,
  listMobileNodes,
  listMobilePcs,
  listProviders,
  listTools,
  loadGraph,
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
  let nodePollTimer: number | null = null
  let chatPollTimer: number | null = null

  const flatGraphs = computed(() => graphInstances.value.flatMap((item) => item.graphs))
  const selectedConfig = computed(() => {
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!nodeId) return null
    return nodeConfigs.value[nodeId] || null
  })

  function setError(value: unknown) {
    error.value = String((value as { message?: unknown })?.message || value || '')
  }

  async function loadPcs() {
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
      pcs.value = await listMobilePcs()
    } catch (e) {
      setError(e)
    } finally {
      loading.value = false
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
      graphInstances.value = await listMobileGraphs(pcId)
    } catch (e) {
      setError(e)
    } finally {
      loading.value = false
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
    await refreshNodeConfigs()
  }

  async function clearSelectedNodeFields(fields: string[]) {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!graphId || !nodeId) throw new Error('Graph and Node selection are required')
    await updateNodeInstanceConfig(nodeId, { clear_fields: fields }, graphId)
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
      startNodePolling()
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

  async function selectNode(node: MobileNode) {
    const nodeId = String(node.id || '').trim()
    if (!nodeId) throw new Error('Node id is required')
    selectedNode.value = node
    view.value = 'chat'
    error.value = ''
    loading.value = true
    try {
      await refreshConversation()
      startChatPolling()
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

  async function clearSelectedNodeMemory() {
    const graphId = String(selectedGraph.value?.id || '').trim()
    const nodeId = String(selectedNode.value?.id || '').trim()
    if (!graphId || !nodeId) throw new Error('Graph and Node selection are required')
    error.value = ''
    loading.value = true
    try {
      await clearNodeInstanceMemory(nodeId, graphId)
      conversation.value = null
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
    stopChatPolling()
    selectedNode.value = null
    conversation.value = null
    view.value = 'nodes'
    startNodePolling()
  }

  function startNodePolling() {
    stopNodePolling()
    nodePollTimer = window.setInterval(() => {
      refreshNodes().catch(setError)
    }, 2500)
  }

  function stopNodePolling() {
    if (nodePollTimer == null) return
    window.clearInterval(nodePollTimer)
    nodePollTimer = null
  }

  function startChatPolling() {
    stopNodePolling()
    stopChatPolling()
    chatPollTimer = window.setInterval(() => {
      Promise.all([refreshNodes(), refreshConversation()]).catch(setError)
    }, 2000)
  }

  function stopChatPolling() {
    if (chatPollTimer == null) return
    window.clearInterval(chatPollTimer)
    chatPollTimer = null
  }

  function stopPolling() {
    stopNodePolling()
    stopChatPolling()
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
