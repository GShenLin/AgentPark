import { getActiveApiBase, requestApiJson } from './api'

export type DoubaoSpeechManagementResponse = {
  ok: boolean
  operation: string
  result: Record<string, unknown>
  speaker_option_count: number
}

export async function runDoubaoSpeechManagement(
  providerId: string,
  operation: string,
  payload: Record<string, unknown>,
): Promise<DoubaoSpeechManagementResponse> {
  return requestApiJson(getActiveApiBase(), `/api/providers/${encodeURIComponent(providerId)}/doubao-speech`, {
    method: 'POST',
    body: JSON.stringify({ operation, payload }),
  }) as Promise<DoubaoSpeechManagementResponse>
}
