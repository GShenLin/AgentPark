import { requestApiJson } from './api'

export type VoiceTarget = { base: string; node: string; graph: string }
export type VoiceAnswer = { session_id: string; sdp: string; model: string }
export type VoiceTaskResult = { status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'; text: string }

export function voiceRequest(target: VoiceTarget, suffix: string, init?: RequestInit) {
  const path = `/api/nodes/instances/${encodeURIComponent(target.node)}/voice${suffix}?graph_id=${encodeURIComponent(target.graph)}`
  return requestApiJson(target.base, path, init)
}

export async function createVoiceCall(target: VoiceTarget, sdp: string, signal: AbortSignal, conference = false): Promise<VoiceAnswer> {
  const result = await voiceRequest(target, '', { method: 'POST', body: JSON.stringify({ sdp, conference }), signal })
  if (typeof result?.session_id !== 'string' || typeof result?.sdp !== 'string' || typeof result?.model !== 'string') {
    throw new Error('语音服务返回了无效的连接信息。')
  }
  return result
}

export async function submitVoiceTask(target: VoiceTarget, session: string, id: string, text: string, signal: AbortSignal): Promise<string> {
  const result = await voiceRequest(target, `/${encodeURIComponent(session)}/tasks`, {
    method: 'POST', body: JSON.stringify({ delegation_id: id, text }), signal,
  })
  if (typeof result?.request_id !== 'string') throw new Error('语音任务未返回有效编号。')
  return result.request_id
}

export async function getVoiceTask(target: VoiceTarget, session: string, id: string, signal: AbortSignal): Promise<VoiceTaskResult> {
  const result = await voiceRequest(target, `/${encodeURIComponent(session)}/tasks/${encodeURIComponent(id)}`, { signal })
  if (!['queued', 'running', 'completed', 'failed', 'cancelled'].includes(result?.status) || typeof result?.text !== 'string') {
    throw new Error('语音任务返回了无效的状态。')
  }
  return result
}
