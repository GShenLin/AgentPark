import { getActiveApiBase } from './api'

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

async function requestJson(path: string, init?: RequestInit) {
  const res = await fetch(`${getActiveApiBase()}${path}`, {
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
