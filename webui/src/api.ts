import type {
  FileListResponse,
  AgentProfile,
  AgentProfileListResponse,
  GraphConfig,
  GraphInfo,
  GraphProfile,
  GraphProfileListResponse,
  MessageEnvelope,
  MobileGraphInstance,
  MobileNode,
  MobileNodeConversation,
  MobilePc,
  NodeConfigChangeResponse,
  NodeInfo,
  NodeInstanceConfig,
  NodeInstanceConfigListResponse,
  NodeInstanceState,
  NodeRunStatus,
  NodeTemplate,
  PasteAgentConfig,
  PendingNodeInput,
  ProviderInfo,
  RemoteEndpoint,
  RunInfo,
  UserInteractionRequest,
} from './apiTypes'

export type {
  FileItem,
  FileListResponse,
  AgentProfile,
  AgentProfileListResponse,
  GraphConfig,
  GraphInfo,
  GraphLink,
  GraphLinkEndpoint,
  GraphNode,
  GraphProfile,
  GraphProfileListResponse,
  GraphProfileNodeConfig,
  MessageEnvelope,
  MessagePart,
  MobileGraph,
  MobileGraphInstance,
  MobileNode,
  MobileNodeConversation,
  MobilePc,
  MobilePcInstance,
  NodeConfigChangeResponse,
  NodeInfo,
  NodeInstanceConfig,
  NodeInstanceConfigListResponse,
  NodeInstanceState,
  NodeRunStatus,
  NodeTemplate,
  PasteAgentConfig,
  PendingNodeInput,
  ProviderRequestSummary,
  ProviderInfo,
  RemoteEndpoint,
  ResourceKind,
  RuntimeEvent,
  RuntimeNoticeEvent,
  RuntimeToolCall,
  RunInfo,
  ToolRuntimeEvent,
  UserInteractionField,
  UserInteractionRequest,
} from './apiTypes'

const DEFAULT_API_BASE = (import.meta as any).env?.VITE_API_BASE || ''
const ACTIVE_REMOTE_KEY = 'aitools.activeRemoteBaseUrl'

function readActiveApiBase() {
  try {
    return window.localStorage.getItem(ACTIVE_REMOTE_KEY) || DEFAULT_API_BASE
  } catch {
    return DEFAULT_API_BASE
  }
}

export function setActiveApiBase(baseUrl: string) {
  try {
    window.localStorage.setItem(ACTIVE_REMOTE_KEY, String(baseUrl || '').replace(/\/$/, ''))
  } catch {
    // ignore local storage errors
  }
}

export function getActiveApiBase() {
  return readActiveApiBase()
}

async function requestJson(baseUrl: string, path: string, init?: RequestInit) {
  const res = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let detail = text.trim()
    if (detail) {
      try {
        const parsed = JSON.parse(detail)
        if (parsed && typeof parsed === 'object' && 'detail' in parsed) {
          detail = typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail)
        }
      } catch {
        // Keep the raw response body when it is not JSON.
      }
    }
    throw new Error(detail ? `HTTP ${res.status}: ${detail}` : `HTTP ${res.status}`)
  }
  return res.json()
}

async function apiFetch(path: string, init?: RequestInit) {
  return requestJson(readActiveApiBase(), path, init)
}

async function remoteConfigFetch(path: string, init?: RequestInit) {
  return requestJson(DEFAULT_API_BASE, path, init)
}

export async function restartServer(): Promise<{ ok: boolean }> {
  return remoteConfigFetch('/api/system/restart', { method: 'POST' })
}

export async function listRemotes(): Promise<RemoteEndpoint[]> {
  const res = await remoteConfigFetch('/api/remotes')
  return (res.remotes || []) as RemoteEndpoint[]
}

export async function addRemote(payload: {
  name: string
  host: string
  port: number | string
}): Promise<{ ok: boolean; remote: RemoteEndpoint; remotes: RemoteEndpoint[] }> {
  return remoteConfigFetch('/api/remotes', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function deleteRemote(remoteId: string): Promise<{ ok: boolean; remotes: RemoteEndpoint[] }> {
  return remoteConfigFetch(`/api/remotes/${encodeURIComponent(remoteId)}`, { method: 'DELETE' })
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

export async function listUserInteractions(): Promise<UserInteractionRequest[]> {
  const res = await apiFetch('/api/user-interactions?status=pending')
  return (res.requests || []) as UserInteractionRequest[]
}

export async function submitUserInteraction(
  requestId: string,
  response: Record<string, unknown>,
): Promise<{ ok: boolean; request: UserInteractionRequest }> {
  return apiFetch(`/api/user-interactions/${encodeURIComponent(requestId)}/submit`, {
    method: 'POST',
    body: JSON.stringify({ status: 'submitted', response }),
  })
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

export async function cloneNodeInstance(
  nodeId: string,
  graphId: string,
  newNodeId: string,
  newName?: string,
  ui?: { x: number; y: number },
): Promise<{ ok: boolean; source_node_id: string; node_id: string; graph_id: string; type_id: string; config_path: string }> {
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/clone?graph_id=${encodeURIComponent(graphId)}`, {
    method: 'POST',
    body: JSON.stringify({
      new_node_id: newNodeId,
      new_name: newName,
      ui,
    }),
  })
}

export async function openNodeInstanceFolder(
  nodeId: string,
  graphId: string,
): Promise<{ ok: boolean; node_id: string; graph_id: string; path: string; source: 'working_path' | 'node_folder' }> {
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/open-folder?graph_id=${encodeURIComponent(graphId)}`, {
    method: 'POST',
  })
}

export async function clearNodeInstanceMemory(
  nodeId: string,
  graphId: string,
): Promise<{ ok: boolean; node_id: string; graph_id: string; cleared_files: number; cleared_summary_fields?: string[] }> {
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/clear-memory?graph_id=${encodeURIComponent(graphId)}`, {
    method: 'POST',
  })
}

export async function listNodeInstanceConfigs(graphId: string, sinceVersion = 0): Promise<NodeInstanceConfigListResponse> {
  const query = new URLSearchParams({ graph_id: graphId })
  if (sinceVersion > 0) query.set('since_version', String(Math.floor(sinceVersion)))
  const res = await apiFetch(`/api/nodes/instances/configs?${query.toString()}`)
  return {
    nodes: (res.nodes || []) as NodeInstanceConfig[],
    node_ids: Array.isArray(res.node_ids) ? res.node_ids.map((item: unknown) => String(item)) : undefined,
    version: Number(res.version || 0),
    partial: !!res.partial,
  }
}

export async function updateNodeInstanceConfig(
  nodeId: string,
  payload: {
    fields?: Record<string, unknown>
    clear_fields?: string[]
    schema?: Record<string, any>
    ui?: { x?: number; y?: number }
  },
  graphId: string,
): Promise<NodeConfigChangeResponse> {
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
  action: 'start' | 'stop' | 'send_input',
  graphId: string,
  extraPayload: Record<string, unknown> = {},
): Promise<{ ok: boolean; state: NodeInstanceState }> {
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/control?graph_id=${encodeURIComponent(graphId)}`, {
    method: 'POST',
    body: JSON.stringify({ action, ...extraPayload }),
  })
}

export async function sendNodeInteractiveInput(
  nodeId: string,
  graphId: string,
  payload: {
    session_id: string
    text?: string
    append_newline?: boolean
    send_eof?: boolean
    send_ctrl_c?: boolean
  },
): Promise<{ ok: boolean }> {
  return controlNodeInstance(nodeId, 'send_input', graphId, payload) as Promise<{ ok: boolean }>
}

export type ChannelReceiverStatus = {
  ok?: boolean
  key?: string
  running?: boolean
  channel?: string
  account_id?: string
  last_error?: string
  last_message_at?: string
}

export type ChannelLoginStartResponse = {
  session_key: string
  qrcode_url: string
  message?: string
}

export type ChannelLoginWaitResponse = {
  connected: boolean
  status?: string
  account_id?: string
  message?: string
}

export async function controlChannelReceiver(
  graphId: string,
  nodeId: string,
  action: 'start' | 'stop' | 'status',
): Promise<ChannelReceiverStatus> {
  return apiFetch(`/api/channels/receivers/${encodeURIComponent(graphId)}/${encodeURIComponent(nodeId)}/control`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
}

export async function startChannelLogin(
  graphId: string,
  nodeId: string,
  accountId?: string,
  force = false,
): Promise<ChannelLoginStartResponse> {
  return apiFetch(`/api/channels/receivers/${encodeURIComponent(graphId)}/${encodeURIComponent(nodeId)}/login/start`, {
    method: 'POST',
    body: JSON.stringify({ account_id: accountId || '', force }),
  })
}

export async function waitChannelLogin(
  graphId: string,
  nodeId: string,
  sessionKey: string,
  timeoutSeconds = 60,
): Promise<ChannelLoginWaitResponse> {
  return apiFetch(`/api/channels/receivers/${encodeURIComponent(graphId)}/${encodeURIComponent(nodeId)}/login/wait`, {
    method: 'POST',
    body: JSON.stringify({ session_key: sessionKey, timeout_seconds: timeoutSeconds }),
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

export async function loadGraph(graphId: string, options?: { ifVersion?: number }): Promise<GraphConfig> {
  const query = new URLSearchParams()
  const ifVersion = Number(options?.ifVersion || 0)
  if (ifVersion > 0) query.set('if_version', String(Math.floor(ifVersion)))
  const suffix = query.toString() ? `?${query.toString()}` : ''
  const res = await apiFetch(`/api/graphs/${encodeURIComponent(graphId)}${suffix}`)
  return res.graph as GraphConfig
}

export async function saveGraph(
  graphId: string,
  graph: GraphConfig,
  options?: { saveReason?: string; sourceGraphId?: string },
): Promise<GraphInfo> {
  const body: Record<string, unknown> = { graph }
  const saveReason = String(options?.saveReason || '').trim()
  if (saveReason) {
    body.save_reason = saveReason
  }
  const sourceGraphId = String(options?.sourceGraphId || '').trim()
  if (sourceGraphId) {
    body.source_graph_id = sourceGraphId
  }
  const res = await apiFetch(`/api/graphs/${encodeURIComponent(graphId)}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return res.graph as GraphInfo
}

export async function deleteGraph(graphId: string): Promise<{ ok: boolean; graph_id: string; deleted: boolean }> {
  return apiFetch(`/api/graphs/${encodeURIComponent(graphId)}`, { method: 'DELETE' })
}

export async function listAgentProfiles(): Promise<AgentProfile[]> {
  const res = await apiFetch('/api/profiles/agents') as AgentProfileListResponse
  return res.profiles || []
}

export async function saveAgentProfileFromNode(payload: {
  graph_id: string
  node_id: string
  profile_id: string
  profile_name?: string
}): Promise<{ ok: boolean; profile: AgentProfile }> {
  return apiFetch('/api/profiles/agents/from-node', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function listGraphProfiles(): Promise<GraphProfile[]> {
  const res = await apiFetch('/api/profiles/graphs') as GraphProfileListResponse
  return res.profiles || []
}

export async function saveGraphProfileFromGraph(payload: {
  graph_id: string
  profile_id: string
  profile_name?: string
}): Promise<{ ok: boolean; profile: GraphProfile }> {
  return apiFetch('/api/profiles/graphs/from-graph', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function createGraphFromProfile(
  profileId: string,
  graphId: string,
): Promise<{ ok: boolean; graph: GraphConfig; profile: GraphProfile }> {
  return apiFetch(`/api/profiles/graphs/${encodeURIComponent(profileId)}/create`, {
    method: 'POST',
    body: JSON.stringify({ graph_id: graphId }),
  })
}

export async function startGraphRunner(graphId: string): Promise<{ ok: boolean; graph_id: string }> {
  return apiFetch(`/api/graphs/${encodeURIComponent(graphId)}/runner/start`, { method: 'POST' })
}

export function graphEventsStreamUrl(graphId: string): string {
  return `${readActiveApiBase()}/api/graphs/${encodeURIComponent(graphId)}/events/stream`
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
  const baseUrl = getActiveApiBase()
  let res: any
  try {
    res = await apiFetch('/api/paste-agent/config')
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || 'unknown error')
    throw new Error(`Failed to load PasteAgent config from ${baseUrl || 'current origin'}: ${message}`)
  }
  if (!res || typeof res !== 'object' || !res.config || typeof res.config !== 'object') {
    throw new Error(`PasteAgent config response from ${baseUrl || 'current origin'} is missing object field "config"`)
  }
  return res.config as PasteAgentConfig
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
  live_message?: string
}> {
  const query = graphId ? `&graph_id=${encodeURIComponent(graphId)}` : ''
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/memory?max_chars=${maxChars}${query}`)
}

export async function deleteNodeInstanceMemoryMessage(
  nodeId: string,
  messageId: string,
  graphId?: string,
): Promise<{ ok: boolean; deleted: number; message_id: string }> {
  const query = graphId ? `?graph_id=${encodeURIComponent(graphId)}` : ''
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/memory/messages/${encodeURIComponent(messageId)}${query}`, {
    method: 'DELETE',
  })
}

export async function getNodeInstanceLive(
  nodeId: string,
  graphId?: string,
): Promise<{ node_id: string; graph_id: string; live_message: string }> {
  const query = graphId ? `?graph_id=${encodeURIComponent(graphId)}` : ''
  return apiFetch(`/api/nodes/instances/${encodeURIComponent(nodeId)}/live${query}`)
}

export function nodeInstanceLiveStreamUrl(nodeId: string, graphId?: string): string {
  const query = graphId ? `?graph_id=${encodeURIComponent(graphId)}` : ''
  return `${readActiveApiBase()}/api/nodes/instances/${encodeURIComponent(nodeId)}/live/stream${query}`
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

export async function deleteMobileNodeMessage(
  pcId: string,
  graphId: string,
  nodeId: string,
  messageId: string,
): Promise<{ ok: boolean; deleted: number; message_id: string }> {
  return apiFetch(
    `/api/mobile/pcs/${encodeURIComponent(pcId)}/graphs/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(nodeId)}/messages/${encodeURIComponent(messageId)}`,
    { method: 'DELETE' },
  )
}
