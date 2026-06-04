import type {
  FileListResponse,
  GraphConfig,
  GraphInfo,
  MessageEnvelope,
  MobileGraphInstance,
  MobileNode,
  MobileNodeConversation,
  MobilePc,
  NodeInfo,
  NodeInstanceConfig,
  NodeInstanceState,
  NodeRunStatus,
  NodeTemplate,
  PasteAgentConfig,
  PendingNodeInput,
  ProviderInfo,
  RunInfo,
} from './apiTypes'

export type {
  FileItem,
  FileListResponse,
  GraphConfig,
  GraphInfo,
  GraphLink,
  GraphLinkEndpoint,
  GraphNode,
  MessageEnvelope,
  MessagePart,
  MobileGraph,
  MobileGraphInstance,
  MobileNode,
  MobileNodeConversation,
  MobilePc,
  MobilePcInstance,
  NodeInfo,
  NodeInstanceConfig,
  NodeInstanceState,
  NodeRunStatus,
  NodeTemplate,
  PasteAgentConfig,
  PendingNodeInput,
  ProviderInfo,
  ResourceKind,
  RuntimeEvent,
  RuntimeNoticeEvent,
  RuntimeToolCall,
  RunInfo,
  ToolRuntimeEvent,
} from './apiTypes'

const API_BASE = (import.meta as any).env?.VITE_API_BASE || ''

async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function listRuns(): Promise<RunInfo[]> {
  const data = await apiFetch('/api/runs')
  return (data?.runs || []) as RunInfo[]
}

export async function createRun(task: string): Promise<RunInfo> {
  const data = await apiFetch('/api/runs', { method: 'POST', body: JSON.stringify({ task }) })
  return data.run as RunInfo
}

export async function getRun(taskId: number): Promise<{ run: RunInfo }> {
  return apiFetch(`/api/runs/${taskId}`)
}

export async function getLeaderMemory(
  taskId: number,
  maxChars = 20000,
): Promise<{ memory_path: string | null; text: string }> {
  return apiFetch(`/api/runs/${taskId}/leader/memory?max_chars=${maxChars}`)
}

export async function sendLeaderMessage(taskId: number, message: string): Promise<void> {
  await apiFetch(`/api/runs/${taskId}/leader/messages`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

export async function listProviders(): Promise<ProviderInfo[]> {
  const res = await apiFetch('/api/providers')
  return res.providers
}

export async function listTools(): Promise<string[]> {
  const res = await apiFetch('/api/tools')
  return res.tools
}

export async function listNodes(): Promise<NodeInfo[]> {
  const res = await apiFetch('/api/nodes')
  return (res.nodes || []) as NodeInfo[]
}

export async function getNodeTemplate(typeId: string): Promise<NodeTemplate> {
  return apiFetch(`/api/nodes/templates/${encodeURIComponent(typeId)}`) as Promise<NodeTemplate>
}

export async function createNodeInstance(
  nodeId: string,
  typeId: string,
  name: string,
  graphId: string,
  ui?: { x: number; y: number },
): Promise<{ ok: boolean; node_id: string; type_id: string; graph_id: string; config_path: string }> {
  return apiFetch('/api/nodes/instances', {
    method: 'POST',
    body: JSON.stringify({
      node_id: nodeId,
      type_id: typeId,
      name,
      graph_id: graphId,
      ui,
    }),
  })
}

export async function deleteNodeInstance(nodeId: string, graphId: string): Promise<void> {
  await apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}?graph_id=${encodeURIComponent(graphId)}`, { method: 'DELETE' })
}

export async function renameNodeInstance(
  nodeId: string,
  graphId: string,
  newNodeId: string,
  newName?: string,
): Promise<{ ok: boolean; old_node_id: string; node_id: string; graph_id: string; type_id: string; config_path: string }> {
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/rename?graph_id=${encodeURIComponent(graphId)}`, {
    method: 'POST',
    body: JSON.stringify({
      new_node_id: newNodeId,
      new_name: newName,
    }),
  })
}

export async function listNodeInstanceConfigs(graphId: string): Promise<NodeInstanceConfig[]> {
  const res = await apiFetch(`/api/nodes/instances/configs?graph_id=${encodeURIComponent(graphId)}`)
  return (res.nodes || []) as NodeInstanceConfig[]
}

export async function updateNodeInstanceConfig(
  nodeId: string,
  payload: { fields?: Record<string, unknown>; schema?: Record<string, any>; ui?: { x?: number; y?: number } },
  graphId: string,
): Promise<{ ok: boolean }> {
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/config?graph_id=${encodeURIComponent(graphId)}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function setNodeInstanceState(
  nodeId: string,
  state: NodeInstanceState,
  graphId: string,
): Promise<{ ok: boolean; state: NodeInstanceState }> {
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/state?graph_id=${encodeURIComponent(graphId)}`, {
    method: 'POST',
    body: JSON.stringify({ state }),
  })
}

export async function controlNodeInstance(
  nodeId: string,
  action: 'start' | 'stop',
  graphId: string,
): Promise<{ ok: boolean; state: NodeInstanceState }> {
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/control?graph_id=${encodeURIComponent(graphId)}`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
}

export async function enqueueNodeInstancePending(
  nodeId: string,
  input: PendingNodeInput,
  graphId: string,
): Promise<{ ok: boolean; pending_count: number }> {
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/pending?graph_id=${encodeURIComponent(graphId)}`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function popNodeInstancePending(
  nodeId: string,
  graphId: string,
): Promise<{ ok: boolean; item: PendingNodeInput | null }> {
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/pending/pop?graph_id=${encodeURIComponent(graphId)}`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export async function runNode(
  nodeId: string,
  input: string | MessageEnvelope,
  context?: Record<string, unknown>,
): Promise<{ output: string; message?: MessageEnvelope }> {
  return apiFetch('/api/nodes/run', {
    method: 'POST',
    body: JSON.stringify({ node_id: nodeId, input, context }),
  })
}

export async function startNodeRun(
  nodeId: string,
  input: string | MessageEnvelope,
  context?: Record<string, unknown>,
): Promise<{ run_id: string }> {
  return apiFetch('/api/nodes/run_async', {
    method: 'POST',
    body: JSON.stringify({ node_id: nodeId, input, context }),
  })
}

export async function getNodeRun(
  runId: string,
): Promise<{ status: NodeRunStatus; output?: string; message?: MessageEnvelope; error?: string }> {
  return apiFetch(`/api/nodes/run/${encodeURIComponent(runId)}`)
}

export async function stopNodeRun(runId: string): Promise<{ status: NodeRunStatus }> {
  return apiFetch(`/api/nodes/run/${encodeURIComponent(runId)}/stop`, {
    method: 'POST',
  })
}

export async function listGraphs(): Promise<GraphInfo[]> {
  const res = await apiFetch('/api/graphs')
  return (res.graphs || []) as GraphInfo[]
}

export async function loadGraph(graphId: string): Promise<GraphConfig> {
  const res = await apiFetch(`/api/graphs/${encodeURIComponent(graphId)}`)
  return res.graph as GraphConfig
}

export async function saveGraph(
  graphId: string,
  graph: GraphConfig,
  options?: { saveReason?: string },
): Promise<GraphInfo> {
  const body: Record<string, unknown> = { graph }
  const saveReason = String(options?.saveReason || '').trim()
  if (saveReason) {
    body.save_reason = saveReason
  }
  const res = await apiFetch(`/api/graphs/${encodeURIComponent(graphId)}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return res.graph as GraphInfo
}

export async function startGraphRunner(graphId: string): Promise<{ ok: boolean; graph_id: string }> {
  return apiFetch(`/api/graphs/${encodeURIComponent(graphId)}/runner/start`, { method: 'POST' })
}

export async function emitGraph(
  graphId: string,
  fromId: string,
  payload: string | MessageEnvelope,
): Promise<{ ok: boolean; queued: boolean; trace_id?: string; output?: string }> {
  return apiFetch(`/api/graphs/${encodeURIComponent(graphId)}/emit`, {
    method: 'POST',
    body: JSON.stringify({ from_id: fromId, payload }),
  })
}

export async function getStartupGraphConfig(): Promise<{ graph_id: string; graph_name: string }> {
  return apiFetch('/api/graphs/startup/config')
}

export async function setStartupGraphConfig(graphId: string, graphName?: string): Promise<{ ok: boolean; graph_id: string; graph_name: string }> {
  return apiFetch('/api/graphs/startup/config', {
    method: 'POST',
    body: JSON.stringify({ graph_id: graphId, graph_name: graphName }),
  })
}

export async function getPasteAgentConfig(): Promise<PasteAgentConfig> {
  const res = await apiFetch('/api/paste-agent/config')
  return (res?.config || {}) as PasteAgentConfig
}

export async function updatePasteAgentConfig(payload: Partial<PasteAgentConfig>): Promise<{ ok: boolean; config: PasteAgentConfig }> {
  return apiFetch('/api/paste-agent/config', {
    method: 'POST',
    body: JSON.stringify(payload || {}),
  })
}

export async function getNodeInstanceMemory(
  nodeId: string,
  maxChars = 20000,
  graphId?: string,
): Promise<{
  memory_path: string | null
  messages_path?: string | null
  text: string
  messages?: MessageEnvelope[]
  state?: NodeInstanceState
  last_message?: string
}> {
  const query = graphId ? `&graph_id=${encodeURIComponent(graphId)}` : ''
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/memory?max_chars=${maxChars}${query}`)
}

export async function listPrompts(): Promise<string[]> {
  const data = await apiFetch('/api/config/prompts')
  return (data?.prompts || []) as string[]
}

export async function getPrompt(filename: string): Promise<string> {
  const data = await apiFetch(`/api/config/prompts/${filename}`)
  return (data?.content || '') as string
}

export async function savePrompt(filename: string, content: string): Promise<void> {
  await apiFetch('/api/config/prompts', {
    method: 'POST',
    body: JSON.stringify({ filename, content }),
  })
}

export async function listFiles(path?: string, search?: string): Promise<FileListResponse> {
  let url = path ? `/api/files?path=${encodeURIComponent(path)}` : '/api/files'
  if (search) {
    url += (path ? '&' : '?') + `search=${encodeURIComponent(search)}`
  }
  return apiFetch(url)
}

export async function selectFolder(initialPath?: string): Promise<{ ok: boolean; path: string }> {
  return apiFetch('/api/files/select-folder', {
    method: 'POST',
    body: JSON.stringify({ initial_path: initialPath || '' }),
  })
}

export async function readFile(path: string): Promise<{ content: string; path: string }> {
  return apiFetch(`/api/files/read?path=${encodeURIComponent(path)}`)
}

export async function saveFile(path: string, content: string): Promise<void> {
  await apiFetch('/api/files/write', {
    method: 'POST',
    body: JSON.stringify({ path, content }),
  })
}

export async function renameFilePath(oldPath: string, newPath: string): Promise<void> {
  await apiFetch('/api/files/rename', {
    method: 'POST',
    body: JSON.stringify({ old_path: oldPath, new_path: newPath }),
  })
}

export async function deleteFilePath(path: string, recursive = true): Promise<void> {
  await apiFetch('/api/files/delete', {
    method: 'POST',
    body: JSON.stringify({ path, recursive }),
  })
}

export async function listMobilePcs(): Promise<MobilePc[]> {
  const res = await apiFetch('/api/mobile/pcs')
  return (res.pcs || []) as MobilePc[]
}

export async function listMobileGraphs(pcId: string): Promise<MobileGraphInstance[]> {
  const res = await apiFetch(`/api/mobile/pcs/${encodeURIComponent(pcId)}/graphs`)
  return (res.instances || []) as MobileGraphInstance[]
}

export async function listMobileNodes(pcId: string, graphId: string): Promise<MobileNode[]> {
  const res = await apiFetch(`/api/mobile/pcs/${encodeURIComponent(pcId)}/graphs/${encodeURIComponent(graphId)}/nodes`)
  return (res.nodes || []) as MobileNode[]
}

export async function getMobileNodeConversation(
  pcId: string,
  graphId: string,
  nodeId: string,
  maxChars = 20000,
): Promise<MobileNodeConversation> {
  return apiFetch(
    `/api/mobile/pcs/${encodeURIComponent(pcId)}/graphs/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(nodeId)}/conversation?max_chars=${maxChars}`,
  ) as Promise<MobileNodeConversation>
}

export async function sendMobileNodeMessage(
  pcId: string,
  graphId: string,
  nodeId: string,
  message: string | MessageEnvelope,
): Promise<{ ok: boolean; queued: boolean; trace_id?: string }> {
  return apiFetch(`/api/mobile/pcs/${encodeURIComponent(pcId)}/graphs/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(nodeId)}/messages`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}
