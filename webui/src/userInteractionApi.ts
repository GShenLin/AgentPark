import { getActiveApiBase, requestApiJson } from './api'
import type { UserInteractionRequest } from './apiTypes'

export async function listUserInteractions(): Promise<UserInteractionRequest[]> {
  const result = await requestApiJson(getActiveApiBase(), '/api/user-interactions?status=pending')
  return result.requests as UserInteractionRequest[]
}

export async function getUserInteraction(requestId: string): Promise<UserInteractionRequest> {
  const result = await requestApiJson(getActiveApiBase(), `/api/user-interactions/${encodeURIComponent(requestId)}`)
  return result.request as UserInteractionRequest
}

export async function submitUserInteraction(requestId: string, response: Record<string, unknown>,
  status: 'submitted' | 'cancelled' = 'submitted'): Promise<{ ok: boolean; request: UserInteractionRequest }> {
  return requestApiJson(getActiveApiBase(), `/api/user-interactions/${encodeURIComponent(requestId)}/submit`, {
    method: 'POST', body: JSON.stringify({ status, response }),
  })
}
