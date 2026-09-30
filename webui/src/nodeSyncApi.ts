import { getActiveApiBase, requestApiJson } from './api'

export interface SyncRemote {
  id: string; name: string; kind: 'local' | 'lan' | 'cloud'
  address: string; available: boolean; state: string
}
export interface SyncCloudStatus { connected: boolean; origin: string }
export function syncRemoteLabel(remote: SyncRemote) {
  return remote.kind === 'cloud' ? `${remote.name} · 远程设备 · ${remote.state}`
    : `${remote.name} · ${remote.kind === 'local' ? '本机' : '手动远端'} · ${remote.address}`
}
export function needsSyncUsername(remote: string) {
  return remote !== 'default' && !remote.startsWith('cloud:')
}

export interface SyncSelection { remote_id: string; graph_id: string; node_id: string | null }
export interface SyncJob {
  id: string
  selection: { source: SyncSelection; target: SyncSelection }
  state: 'preparing' | 'ready' | 'applying' | 'complete' | 'failed' | 'interrupted'
  action?: 'preview' | 'commit'
  phase: string
  error: string
  completed_nodes: number
  result: null | {
    added: number; updated: number; unchanged: number; nodes: number
    message_bytes: number; attachment_bytes: number; attachments: number
    structure_files: number; groups_changed: number
    structure_changes: string[]
    conflicts: string[]; warnings: string[]
  }
}
export interface SyncOption { id: string; name: string }

export function sameSyncSelection(a: SyncSelection, b: SyncSelection) {
  return a.remote_id === b.remote_id && a.graph_id === b.graph_id && a.node_id === b.node_id
}

export function nodeSyncClient() {
  // Capture this host; selector changes never modify the application's active remote.
  const base = getActiveApiBase()
  const call = (path: string, init?: RequestInit) => requestApiJson(base, `/api/node-sync${path}`, init)
  const post = (path: string, body = {}) => call(path, { method: 'POST', body: JSON.stringify(body) })
  return {
    storageKey: `agentpark.node-sync.job:${base}`,
    remotes: async (): Promise<SyncRemote[]> => (await call('/remotes')).remotes,
    cloudStatus: (): Promise<SyncCloudStatus> => call('/cloud'),
    cloudLogin: (password: string): Promise<SyncCloudStatus> => post('/cloud/login', { password }),
    cloudLogout: (): Promise<SyncCloudStatus> => post('/cloud/logout'),
    graphs: async (remote: string): Promise<SyncOption[]> =>
      (await call(`/catalog/${encodeURIComponent(remote)}`)).graphs,
    nodes: async (remote: string, graph: string): Promise<SyncOption[]> =>
      (await call(`/catalog/${encodeURIComponent(remote)}?graph_id=${encodeURIComponent(graph)}`)).nodes,
    createGraph: (remote: string, id: string, name: string) => post(`/catalog/${encodeURIComponent(remote)}/graphs`, { id, name }),
    preview: (source: SyncSelection, target: SyncSelection): Promise<SyncJob> => post('/jobs', { source, target }),
    job: (id: string): Promise<SyncJob> => call(`/jobs/${encodeURIComponent(id)}`),
    resume: (id: string, action: 'preview' | 'commit'): Promise<SyncJob> => post(`/jobs/${encodeURIComponent(id)}/${action}`),
  }
}
