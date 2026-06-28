import { computed, onBeforeUnmount, ref } from 'vue'
import {
  clearNodeInstanceMemory,
  getMobileNodeConversation,
  listNodeInstanceConfigs,
  listMobileGraphs,
  listMobileNodes,
  listMobilePcs,
  listProviders,
  listTools,
  sendMobileNodeMessage,
  updateNodeInstanceConfig,
  type MessageEnvelope,
  type MobileGraph,
  type MobileGraphInstance,
  type MobileNode,
  type MobileNodeConversation,
  type MobilePc,
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
    if (providers.value.length && availableTools.value.length) return
    const [nextProviders, nextTools] = await Promise.all([
      listProviders(),
      listTools(),
    ])
    providers.value = nextProviders
    availableTools.value = nextTools
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
    refreshCurrent,
    refreshNodeConfigs,
    backToPcs,
    backToGraphs,
    backToNodes,
  }
}
