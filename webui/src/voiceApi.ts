import { requestApiJson } from './api'
import { supportedVoiceProtocols, type VoiceProtocol } from './voice/voiceProtocol'

export type VoiceTarget = { base: string; node: string; graph: string }
export type RtcConnection = { transport: 'volcengine-rtc'; app_id: string; room_id: string; user_id: string; bot_id: string; token: string }
export type VoiceAnswer = { session_id: string; model: string; protocol: VoiceProtocol }
  & ({ transport: 'webrtc'; sdp: string } | RtcConnection)
export type VoiceTaskResult = { status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'; text: string }

export function voiceRequest(target: VoiceTarget, suffix: string, init?: RequestInit) {
  const path = `/api/nodes/instances/${encodeURIComponent(target.node)}/voice${suffix}?graph_id=${encodeURIComponent(target.graph)}`
  return requestApiJson(target.base, path, init)
}

export async function describeVoiceCall(target: VoiceTarget, signal: AbortSignal): Promise<'webrtc' | 'volcengine-rtc'> {
  const result = await voiceRequest(target, '', { signal })
  if (!supportedVoiceProtocols.includes(result?.protocol) || !['webrtc', 'volcengine-rtc'].includes(result?.transport)) {
    throw new Error('语音连接方式不受当前页面支持，请刷新页面。')
  }
  return result.transport
}

export async function controlRtcCall(target: VoiceTarget, session: string, command: { action: 'activate' | 'heartbeat' } | { action: 'screen'; enabled: boolean; fps: number }, signal?: AbortSignal) {
  const result = await voiceRequest(target, `/${encodeURIComponent(session)}/control`, {
    method: 'POST', body: JSON.stringify(command), signal,
  })
  if (result?.ok !== true) throw new Error('火山语音服务未确认控制指令。')
}

export async function createVoiceCall(target: VoiceTarget, sdp: string | undefined, signal: AbortSignal): Promise<VoiceAnswer> {
  const result = await voiceRequest(target, '', { method: 'POST', body: JSON.stringify({ sdp, protocols: supportedVoiceProtocols }), signal })
  if (typeof result?.session_id !== 'string' || typeof result?.model !== 'string') {
    throw new Error('语音服务返回了无效的连接信息。')
  }
  if (!supportedVoiceProtocols.includes(result.protocol)) {
    throw new Error('语音页面版本与服务不一致，请刷新页面，并确认当前网址的前端和后端均已更新。')
  }
  if (result.transport === 'webrtc' && result.protocol !== 'volcengine-rtc-v1' && typeof result.sdp === 'string') return result
  if (result.transport === 'volcengine-rtc' && result.protocol === 'volcengine-rtc-v1'
      && ['app_id', 'room_id', 'user_id', 'bot_id', 'token'].every(key => typeof result[key] === 'string' && result[key].length > 0)) return result
  throw new Error('语音服务返回的传输协议与连接信息不匹配。')
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

export async function publishVoiceTaskUpdate(target: VoiceTarget, session: string, id: string, signal: AbortSignal): Promise<VoiceTaskResult> {
  const result = await voiceRequest(target, `/${encodeURIComponent(session)}/tasks/${encodeURIComponent(id)}/updates`, {
    method: 'POST', signal,
  })
  if (!['accepted', 'duplicate'].includes(result?.delivery)
      || !['queued', 'running', 'completed', 'failed', 'cancelled'].includes(result?.status)
      || typeof result?.text !== 'string') {
    throw new Error('语音服务未确认节点状态的回传。')
  }
  return result
}
