import { getActiveApiBase, requestApiJson } from './api'

export type SettingsSectionInfo = {
  id: string
  label: string
  path: string
  filename: string
}

export type SettingsDocument = {
  section: string
  label: string
  path: string
  content: string
  data: Record<string, unknown>
}

export type ProviderLimitFeature = {
  supported: boolean
  reason?: string
  status_code?: number
  supported_values?: string[]
  values?: Record<string, ProviderLimitFeature>
}

export type ProviderLimitEntry = {
  provider_id: string
  type: string
  model: string
  tested_at: string
  accessible: boolean
  status: string
  access_error?: string
  available_model_ids?: string[]
  model_discovery?: ProviderLimitFeature & {
    tested_at?: string
    endpoint?: string
  }
  features: Record<string, ProviderLimitFeature>
  unsupported: Record<string, string | Record<string, string>>
}

export type ProviderLimitDocument = {
  schema_version: number
  generated_at: string
  status?: 'running' | 'finished'
  duration_ms?: number
  completed_providers?: number
  total_providers?: number
  current_provider_id?: string
  model_refresh_status?: 'running' | 'finished'
  model_refresh_completed_providers?: number
  model_refresh_total_providers?: number
  model_refresh_current_provider_id?: string
  path: string
  providers: Record<string, ProviderLimitEntry>
}

export type ProviderLimitTestJob = {
  job_id: string
  kind?: 'limit_test' | 'model_refresh'
  status: 'running' | 'finished' | 'failed' | 'not_found'
  started_at?: string
  finished_at?: string
  provider_id?: string
  index?: number
  total?: number
  duration_ms?: number
  error?: string
  result?: ProviderLimitDocument | null
}

export type ProviderLimitTestResponse = {
  ok: boolean
  job: ProviderLimitTestJob
  result: ProviderLimitDocument
}

export type ToolStatsToolSummary = {
  tool_name: string
  total: number
  success: number
  failure: number
  statuses: Record<string, number>
  last_call_at: string
  last_status: string
  last_error: string
  last_result_preview: string
}

export type ToolStatsProviderSummary = {
  provider_id: string
  total: number
  success: number
  failure: number
  statuses: Record<string, number>
  tools: Record<string, ToolStatsToolSummary>
  last_call_at: string
}

export type ToolStatsSummary = {
  updated_at?: string
  providers: Record<string, ToolStatsProviderSummary>
}

export type ToolCallStatRecord = {
  recorded_at: string
  provider_id: string
  graph_id: string
  node_id: string
  tool_name: string
  call_id: string
  success: boolean
  status: string
  error: string
  duration_ms: number | null
  started_at: string
  completed_at: string
  result_preview: string
  result_chars: number | null
}

export type ToolStatsDocument = {
  summary: ToolStatsSummary
  recent_calls: ToolCallStatRecord[]
}

async function requestJson(path: string, init?: RequestInit) {
  return requestApiJson(getActiveApiBase(), path, init)
}

export async function listSettingsSections(): Promise<SettingsSectionInfo[]> {
  const res = await requestJson('/api/settings')
  return (res.sections || []) as SettingsSectionInfo[]
}

export async function getSettingsSection(section: string): Promise<SettingsDocument> {
  return requestJson(`/api/settings/${encodeURIComponent(section)}`) as Promise<SettingsDocument>
}

export async function updateSettingsSection(section: string, content: string): Promise<SettingsDocument> {
  return requestJson(`/api/settings/${encodeURIComponent(section)}`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  }) as Promise<SettingsDocument>
}

export async function getProviderLimits(): Promise<ProviderLimitDocument> {
  return requestJson('/api/providers/limits') as Promise<ProviderLimitDocument>
}

export async function getToolStats(): Promise<ToolStatsDocument> {
  return requestJson('/api/tool-stats') as Promise<ToolStatsDocument>
}

export async function clearToolStats(): Promise<ToolStatsDocument> {
  return requestJson('/api/tool-stats', { method: 'DELETE' }) as Promise<ToolStatsDocument>
}

export async function startProviderLimitTests(timeoutSeconds = 30): Promise<ProviderLimitTestResponse> {
  return requestJson('/api/providers/limits/test', {
    method: 'POST',
    body: JSON.stringify({ timeout_seconds: timeoutSeconds }),
  }) as Promise<ProviderLimitTestResponse>
}

export async function startProviderModelDiscovery(timeoutSeconds = 30): Promise<ProviderLimitTestResponse> {
  return requestJson('/api/providers/limits/models', {
    method: 'POST',
    body: JSON.stringify({ timeout_seconds: timeoutSeconds }),
  }) as Promise<ProviderLimitTestResponse>
}

export async function getProviderLimitTestJob(jobId: string): Promise<ProviderLimitTestResponse> {
  return requestJson(`/api/providers/limits/test/${encodeURIComponent(jobId)}`) as Promise<ProviderLimitTestResponse>
}
