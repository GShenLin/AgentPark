import { getActiveApiBase, requestApiJson } from '../api'
import type { MessageResource } from '../composables/messageAttachments'

export type GroupBounds = { x: number; y: number; width: number; height: number }
export type GroupMember = { node_id: string; role: string }
export type TaskStatus = 'todo' | 'in_progress' | 'blocked' | 'done'
export type GroupTask = {
  id: string; title: string; description: string; status: TaskStatus; owner_id: string | null
  dependencies: string[]; evidence: string; revision: number; created_at: string; updated_at: string
}
export type AgentGroup = {
  id: string; name: string; objective: string; bounds: GroupBounds; members: GroupMember[]
  tasks: GroupTask[]; revision: number; private: boolean; dissolved: boolean; created_at: string; updated_at: string
}
export type GroupEvent = {
  seq: number; group_id: string; kind: string; actor_id: string | null
  payload: Record<string, unknown>; created_at: string
}
export type GroupDelivery = { event_seq: number; node_id: string; state: 'pending' | 'delivered' | 'cancelled'; attempts: number; last_error: string | null; started_at?: string | null }
export type GroupMessage = { text: string; attachments?: MessageResource[]; request_id: string; recipient_id?: string; intent?: 'action' | 'update' }

function path(graph: string, suffix: string) { return `/api/graphs/${encodeURIComponent(graph)}${suffix}` }
function groupPath(graph: string, group: string, suffix = '') { return path(graph, `/groups/${encodeURIComponent(group)}${suffix}`) }
function request<T>(url: string, method = 'GET', body?: unknown): Promise<T> {
  return requestApiJson(getActiveApiBase(), url, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
}

export const groupApi = {
  list: (graph: string) => request<{ groups: AgentGroup[] }>(path(graph, '/groups')),
  get: (graph: string, group: string) => request<AgentGroup>(groupPath(graph, group)),
  create: (graph: string, body: { name: string; objective: string; members: GroupMember[]; bounds: GroupBounds }) =>
    request<AgentGroup>(path(graph, '/groups'), 'POST', body),
  configure: (graph: string, group: string, body: { expected_revision: number; name?: string; objective?: string; bounds?: GroupBounds }) =>
    request<AgentGroup>(groupPath(graph, group), 'PATCH', body),
  dissolve: (graph: string, group: string, revision: number) =>
    request<{ ok: boolean }>(groupPath(graph, group, `?expected_revision=${revision}`), 'DELETE'),
  updatePlan: (graph: string, group: string, body: { expected_name: string; expected_objective: string; name: string; objective: string }) =>
    request<AgentGroup>(groupPath(graph, group, '/plan'), 'PATCH', body),
  move: (graph: string, node: string, body: { target_group_id: string | null; expected_source: string | null; role?: string }) =>
    request<{ group: AgentGroup | null }>(path(graph, `/group-members/${encodeURIComponent(node)}`), 'PUT', body),
  updateRole: (graph: string, group: string, node: string, body: { expected_role: string; role: string }) =>
    request<AgentGroup>(groupPath(graph, group, `/members/${encodeURIComponent(node)}`), 'PATCH', body),
  events: (graph: string, group: string, after: number, options: { latest?: boolean; before?: number } = {}) =>
    request<{ events: GroupEvent[]; cursor: number; has_older: boolean }>(groupPath(graph, group, `/events?after=${after}&limit=100&latest=${!!options.latest}&before=${options.before || 0}`)),
  deliveries: (graph: string, group: string) => request<{ deliveries: GroupDelivery[] }>(groupPath(graph, group, '/deliveries')),
  send: (graph: string, group: string, body: GroupMessage) =>
    request<GroupEvent>(groupPath(graph, group, '/messages'), 'POST', body),
  createTask: (graph: string, group: string, body: { title: string; description?: string; owner_id?: string | null; dependencies?: string[] }) =>
    request<GroupTask>(groupPath(graph, group, '/tasks'), 'POST', body),
  updateTask: (graph: string, group: string, task: string, body: { expected_revision: number; title?: string; description?: string;
    owner_id?: string | null; status?: TaskStatus; dependencies?: string[]; evidence?: string }) =>
    request<GroupTask>(groupPath(graph, group, `/tasks/${encodeURIComponent(task)}`), 'PATCH', body),
}
