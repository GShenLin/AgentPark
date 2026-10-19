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

export function listNativeHarnessModels(id: 'opencode' | 'antigravity'): Promise<{ models: string[] }> {
  return requestApiJson(getActiveApiBase(), `/api/harnesses/${id}/models`)
}

export type OpenCodeField = 'native_model' | 'native_agent' | 'native_effort'
export type NativeOption = { value: string; label: string }
export type OpenCodeOptions = Record<OpenCodeField, NativeOption[]> & { selection_error: string }

export function getOpenCodeOptions(model: string, agent: string, workingPath: string): Promise<OpenCodeOptions> {
  return requestApiJson(getActiveApiBase(), '/api/harnesses/opencode/config-options', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, agent, working_path: workingPath }),
  })
}
