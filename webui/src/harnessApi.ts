import { getActiveApiBase, requestApiJson } from './api'

export type HarnessInfo = {
  id: string
  name: string
  node_type: string
  package: string
  executable: string
  transport: string
  homepage: string
  session_support: string
  installation: 'npm' | 'hermes-python' | 'antigravity-native'
  status: 'missing' | 'ready' | 'busy' | 'error'
  source: 'managed' | 'external' | 'none'
  version: string
  installed_version: string
  latest_version: string
  update_status: 'unchecked' | 'available' | 'current' | 'error'
  update_error: string
  executable_path: string
  error: string
  can_uninstall: boolean
  can_upgrade: boolean
  upgrade_error: string
}

export type HarnessJob = {
  id: string
  harness_id: string
  action: 'install' | 'upgrade' | 'uninstall'
  status: 'running' | 'completed' | 'failed'
  error: string
  output: string
  harness?: HarnessInfo
  restore_errors?: { node_id: string; error: string }[]
  restored_count?: number
}

export type HarnessProcessState = 'stopped' | 'starting' | 'ready' | 'running' | 'stopping' | 'error'
export type HarnessProcess = {
  harness_id: string
  graph_id: string
  node_id: string
  state: HarnessProcessState
  error: string
}
export const harnessNodeTypes = new Set([
  'codex_node', 'claude_node', 'openclaw_node', 'deepseek_harness_node', 'minimax_code_node',
  'opencode_node', 'antigravity_node', 'pi_node', 'hermes_agent_node',
])
export function listHarnessProcesses(id: string): Promise<{ processes: HarnessProcess[] }> {
  return requestApiJson(getActiveApiBase(), `/api/harnesses/${encodeURIComponent(id)}/processes`)
}
export function getHarnessProcess(nodeId: string, graphId: string): Promise<HarnessProcess> {
  return requestApiJson(getActiveApiBase(), `/api/nodes/instances/${encodeURIComponent(nodeId)}/harness-process?graph_id=${encodeURIComponent(graphId)}`)
}
export function controlHarnessProcess(nodeId: string, graphId: string, action: 'start' | 'stop'): Promise<HarnessProcess> {
  return requestApiJson(getActiveApiBase(), `/api/nodes/instances/${encodeURIComponent(nodeId)}/harness-process?graph_id=${encodeURIComponent(graphId)}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }),
  })
}

export function listHarnesses(): Promise<{ harnesses: HarnessInfo[]; jobs: HarnessJob[] }> {
  return requestApiJson(getActiveApiBase(), '/api/harnesses')
}
export function checkHarness(id: string): Promise<HarnessInfo> {
  return requestApiJson(getActiveApiBase(), `/api/harnesses/${encodeURIComponent(id)}`)
}
export function operateHarness(id: string, action: HarnessJob['action']): Promise<HarnessJob> {
  return requestApiJson(getActiveApiBase(), `/api/harnesses/${encodeURIComponent(id)}/operations`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }),
  })
}
export function getHarnessJob(id: string): Promise<HarnessJob> {
  return requestApiJson(getActiveApiBase(), `/api/harness-jobs/${encodeURIComponent(id)}`)
}
