import { getActiveApiBase, requestApiJson } from './api'

export type WorkBuddyService = {
  state: 'stopped' | 'installing' | 'starting' | 'running' | 'stopping' | 'failed'
  installed: boolean
  error: string
  autoStart: boolean
  port: number
  baseUrl: string
  logPath: string
}
export type WorkBuddyModel = {
  id: string; name: string; description: string
  contextWindow: number; maxTokens: number; supportsImages: boolean; reasoningEfforts: string[]
  billing: { free: boolean; label: string; multiplier: number | null; promotionText: string; promotionEndsAt: string }
}
export type WorkBuddyAccount = { connected: boolean; account: string; models: number }
export function workBuddyService(operation?: string, settings?: { autoStart: boolean; port: number }) {
  return requestApiJson(getActiveApiBase(), '/api/workbuddy/service', operation
    ? { method: 'POST', body: JSON.stringify({ operation, ...settings }) } : undefined) as Promise<WorkBuddyService>
}
export function workBuddyAccount<T>(providerId: string, operation: string, loginId?: string): Promise<T> {
  return requestApiJson(getActiveApiBase(), `/api/providers/${encodeURIComponent(providerId)}/workbuddy`, {
    method: 'POST', body: JSON.stringify({ operation, ...(loginId ? { loginId } : {}) }),
  }) as Promise<T>
}
