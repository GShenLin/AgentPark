import { createApiNetworkError, getActiveApiBase, requestApiJson } from './api'

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
  warnings?: string[]
  active_preset_id?: string
  presets?: ThemePresetInfo[]
}

export type ThemePresetInfo = {
  id: string
  path: string
}

export type ThemePresetCatalog = {
  active_preset_id: string
  presets: ThemePresetInfo[]
}

export type ThemeAssetUploadResponse = {
  ok: boolean
  preset_id: string
  asset_path: string
  path: string
  size: number
}

export type ProviderLimitFeature = {
  supported: boolean
  outcome?: 'supported' | 'unsupported' | 'unreachable' | 'unauthorized' | 'forbidden' | 'rate_limited' | 'provider_error' | 'invalid_response' | 'error' | 'not_tested'
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
  test_channel?: ProviderResolvedTestChannel
  test_endpoint?: string
  accessible: boolean
  status: 'ok' | 'unsupported' | 'unavailable'
  access_error?: string
  available_model_ids?: string[]
  model_discovery?: ProviderLimitFeature & {
    tested_at?: string
    endpoint?: string
  }
  features: Record<string, ProviderLimitFeature>
  unsupported: Record<string, string | Record<string, string>>
  inconclusive?: Record<string, string | Record<string, string>>
  channels?: Record<string, ProviderLimitChannelEntry>
}

export type ProviderLimitChannelEntry = Omit<ProviderLimitEntry, 'channels' | 'available_model_ids' | 'model_discovery'>

export type ProviderLimitDocument = {
  schema_version: number
  generated_at: string
  test_mode?: 'all_channels'
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

export type ProviderPressureEntry = {
  provider_id: string
  type: string
  model: string
  concurrency_limit: number | null
  rpm_limit: number | null
  in_flight: number
  queued: number
  rpm_used: number
  rpm_interval_sec: number | null
  rpm_next_available_in_sec: number
  peak_in_flight: number
  peak_queued: number
  peak_rpm_used: number
  rpm_remaining: number | null
}

export type ProviderPressureDocument = {
  ok: boolean
  window_seconds: number
  providers: ProviderPressureEntry[]
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

export type ProviderTestChannel = 'chat_completions' | 'responses'
export type ProviderResolvedTestChannel = ProviderTestChannel | 'messages' | 'generate_content' | 'native'

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
  agent_event_provider: string
  tool_call_raw: unknown
  tool_call_arguments: Record<string, unknown> | null
  tool_call_arguments_json: string
  result: unknown
  result_preview: string
  result_chars: number | null
  diagnostics: string[]
}

export type ToolFailureSample = {
  recorded_at: string
  call_id: string
  status: string
  category: string
  error: string
  command: string
  arguments: Record<string, unknown> | null
  result_preview: string
}

export type ToolFailureCategorySummary = {
  category: string
  count: number
  tool_count: number
  tools: string[]
}

export type ToolFailureToolSummary = {
  tool_name: string
  failure_count: number
  categories: Record<string, number>
  statuses: Record<string, number>
  reasons: Record<string, number>
  samples: ToolFailureSample[]
}

export type ToolFailureAnalysis = {
  analyzed_call_count: number
  total_failures: number
  affected_tool_count: number
  categories: Array<{ category: string; count: number }>
  statuses: Record<string, number>
  shared_patterns: ToolFailureCategorySummary[]
  tools: Record<string, ToolFailureToolSummary>
}

export type ToolFailureHistory = {
  tool_name: string
  analyzed_call_count: number
  failure_count: number
  calls: ToolCallStatRecord[]
}

export type ToolStatsDocument = {
  summary: ToolStatsSummary
  recent_calls: ToolCallStatRecord[]
  failure_analysis: ToolFailureAnalysis
}

export type DeleteOptionalMemoryResponse = {
  ok: boolean
  returncode: number
  stdout: string
  stderr: string
}

export type CodexAuthStatus = {
  authorized: boolean
  email: string
  planType: string
  accountIdSuffix: string
  expiresAt: string
  needsRefresh: boolean
  authPath: string
  error: string
}

export type CodexLoginStart = {
  started: boolean
  authUrl: string
  port: number
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

export async function listThemePresets(): Promise<ThemePresetCatalog> {
  return requestJson('/api/theme/presets') as Promise<ThemePresetCatalog>
}

export async function loadThemePreset(presetId: string): Promise<SettingsDocument> {
  return requestJson('/api/theme/presets/load', {
    method: 'POST',
    body: JSON.stringify({ preset_id: presetId }),
  }) as Promise<SettingsDocument>
}

export async function saveThemePreset(presetId: string, content: string): Promise<SettingsDocument> {
  return requestJson('/api/theme/presets/save', {
    method: 'POST',
    body: JSON.stringify({ preset_id: presetId, content }),
  }) as Promise<SettingsDocument>
}

export async function uploadThemeAsset(file: File, presetId = ''): Promise<ThemeAssetUploadResponse> {
  const body = new FormData()
  body.append('file', file)
  const safePresetId = String(presetId || '').trim()
  if (safePresetId) {
    body.append('preset_id', safePresetId)
  }

  const baseUrl = getActiveApiBase()
  const path = '/api/theme/assets'
  const init: RequestInit = {
    method: 'POST',
    body,
  }
  let res: Response
  try {
    res = await fetch(`${baseUrl}${path}`, init)
  } catch (error) {
    throw createApiNetworkError(baseUrl, path, init, error)
  }
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
  return res.json() as Promise<ThemeAssetUploadResponse>
}

export async function getProviderLimits(): Promise<ProviderLimitDocument> {
  return requestJson('/api/providers/limits') as Promise<ProviderLimitDocument>
}

export async function getCodexAuthStatus(): Promise<CodexAuthStatus> {
  return requestJson('/api/provider-auth/codex/status') as Promise<CodexAuthStatus>
}

export async function startCodexLogin(): Promise<CodexLoginStart> {
  return requestJson('/api/provider-auth/codex/login', { method: 'POST' }) as Promise<CodexLoginStart>
}

export async function getProviderPressure(): Promise<ProviderPressureDocument> {
  return requestJson('/api/providers/pressure') as Promise<ProviderPressureDocument>
}

export async function getToolStats(): Promise<ToolStatsDocument> {
  return requestJson('/api/tool-stats') as Promise<ToolStatsDocument>
}

export async function getToolFailureHistory(toolName: string): Promise<ToolFailureHistory> {
  return requestJson(`/api/tool-stats/failures/${encodeURIComponent(toolName)}`) as Promise<ToolFailureHistory>
}

export async function clearToolStats(): Promise<ToolStatsDocument> {
  return requestJson('/api/tool-stats', { method: 'DELETE' }) as Promise<ToolStatsDocument>
}

export async function deleteOptionalMemory(): Promise<DeleteOptionalMemoryResponse> {
  return requestJson('/api/operational-memory/delete-optional', { method: 'POST' }) as Promise<DeleteOptionalMemoryResponse>
}

export async function startProviderLimitTests(
  timeoutSeconds = 30,
): Promise<ProviderLimitTestResponse> {
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
