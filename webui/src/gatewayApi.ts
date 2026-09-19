import { getActiveApiBase, requestApiJson } from './api'

export type GatewayProtocol = 'responses' | 'chat_completions' | 'messages' | 'images_generations' | 'images_edits'

export type GatewayAccount = {
  id: string
  alias: string
  identity: string
  kind: 'oauth' | 'api_key'
  active: boolean
  needsReauth: boolean
}

export type GatewayProvider = {
  id: string
  model: string
  protocol: 'responses' | 'openai_chat' | 'anthropic' | 'gemini' | 'images'
  protocols: GatewayProtocol[]
  authProvider: string
  accounts: GatewayAccount[]
  kind: 'provider'
}

export type GatewaySourceError = {
  id: string
  error: string
}

export type GatewayModel = {
  id: string
  providerId: string
  accountId: string
  protocols: GatewayProtocol[]
  enabled: boolean
}

export type GatewayKey = {
  id: string
  name: string
  prefix: string
  createdAt: number
}

export type GatewaySettings = {
  enabled: boolean
  requireApiKey: boolean
  models: GatewayModel[]
  keys: GatewayKey[]
  providers: GatewayProvider[]
  sourceErrors: GatewaySourceError[]
}

export type GatewayCreateKeyResponse = {
  created: GatewayKey & { key: string }
  keys: GatewayKey[]
}

export type GatewayTestResponse = {
  ok: boolean
  status: number
  protocol: GatewayProtocol
  model: string
  response: Record<string, unknown>
}

export type GatewayUsageTotals = {
  requestCount: number
  usageRequestCount: number
  missingUsageRequestCount: number
  inputTokens: number
  outputTokens: number
  totalTokens: number
  cachedInputTokens: number
  cacheWriteInputTokens: number
  reasoningOutputTokens: number
}

export type GatewayUsageModel = GatewayUsageTotals & {
  modelId: string
}

export type GatewayUsageIp = GatewayUsageTotals & {
  ip: string
  models: GatewayUsageModel[]
}

export type GatewayUsageStats = {
  date: string
  timezoneOffset: string
  totals: GatewayUsageTotals
  ips: GatewayUsageIp[]
}

function requestJson(path: string, init?: RequestInit) {
  return requestApiJson(getActiveApiBase(), path, init)
}

export async function getGatewaySettings(): Promise<GatewaySettings> {
  return requestJson('/api/gateway') as Promise<GatewaySettings>
}

export async function getGatewayUsage(date: string): Promise<GatewayUsageStats> {
  return requestJson(`/api/gateway/usage/${encodeURIComponent(date)}`) as Promise<GatewayUsageStats>
}

export type GatewaySettingsDraft = Pick<GatewaySettings, 'enabled' | 'requireApiKey' | 'models'>

export async function updateGatewaySettings(payload: GatewaySettingsDraft): Promise<GatewaySettings> {
  return requestJson('/api/gateway', {
    method: 'PUT',
    body: JSON.stringify(payload),
  }) as Promise<GatewaySettings>
}

export async function createGatewayKey(payload: {
  name: string
  key?: string
}): Promise<GatewayCreateKeyResponse> {
  return requestJson('/api/gateway/keys', {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<GatewayCreateKeyResponse>
}

export async function deleteGatewayKey(keyId: string): Promise<{ deleted: boolean; keys: GatewayKey[] }> {
  return requestJson(`/api/gateway/keys/${encodeURIComponent(keyId)}`, {
    method: 'DELETE',
  }) as Promise<{ deleted: boolean; keys: GatewayKey[] }>
}

export async function testGateway(payload: {
  model: string
  protocol: GatewayProtocol
  prompt?: string
  images?: Array<{ image_url: string }>
}): Promise<GatewayTestResponse> {
  return requestJson('/api/gateway/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<GatewayTestResponse>
}
