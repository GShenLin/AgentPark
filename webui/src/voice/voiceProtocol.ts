import { RealtimeDialogue } from './RealtimeDialogue'

export const supportedVoiceProtocols = ['openai-realtime-v1', 'agentpark-voice-v4', 'volcengine-rtc-v1'] as const
export type VoiceProtocol = typeof supportedVoiceProtocols[number]
export type VoiceEvent =
  | { kind: 'ready' }
  | { kind: 'closed' }
  | { kind: 'error'; text: string }
  | { kind: 'transcript'; role: 'user' | 'assistant'; text: string; done: boolean; replace?: boolean }
  | { kind: 'delegation'; id: string; text: string }
  | { kind: 'interrupted'; role?: 'user' | 'assistant' }
  | { kind: 'task-status'; text: string }
  | { kind: 'other' }

export type VoiceProtocolAdapter = {
  parse: (raw: string) => VoiceEvent
} & ({
  resultDelivery: 'data-channel'
  dialogue: RealtimeDialogue
} | { resultDelivery: 'server' })

function parseBridgeEvent(raw: string): VoiceEvent {
  const event = JSON.parse(raw)
  if (!event || typeof event.type !== 'string') throw new Error('语音服务器返回了无效事件。')
  switch (event.type) {
    case 'ready': return { kind: 'ready' }
    case 'closed': return { kind: 'closed' }
    case 'interrupted': return { kind: 'interrupted' }
    case 'task.status':
      if (typeof event.text === 'string') return { kind: 'task-status', text: event.text }
      break
    case 'delegation':
      if (typeof event.id === 'string' && event.id && typeof event.text === 'string' && event.text.trim()) {
        return { kind: 'delegation', id: event.id, text: event.text }
      }
      break
    case 'error':
      if (typeof event.text === 'string') return { kind: 'error', text: event.text }
      break
    case 'transcript':
      if ((event.role === 'user' || event.role === 'assistant') && typeof event.text === 'string'
          && typeof event.done === 'boolean' && typeof event.replace === 'boolean') {
        return { kind: 'transcript', role: event.role, text: event.text, done: event.done, replace: event.replace }
      }
      break
  }
  throw new Error(`语音事件 ${JSON.stringify(event.type).slice(0, 80)} 不符合 agentpark-voice-v4 协议，请刷新页面后重试。`)
}

export function voiceProtocol(protocol: VoiceProtocol, send: (event: object) => void = () => { throw new Error('Realtime 发送通道未绑定。') }): VoiceProtocolAdapter {
  switch (protocol) {
    case 'volcengine-rtc-v1': return { resultDelivery: 'server', parse: () => { throw new Error('火山 RTC 使用二进制 TLV 协议，不能读取文本数据通道。') } }
    case 'openai-realtime-v1': {
      const dialogue = new RealtimeDialogue(send)
      return { parse: raw => dialogue.parse(raw), resultDelivery: 'data-channel', dialogue }
    }
    case 'agentpark-voice-v4': return {
      parse: parseBridgeEvent,
      resultDelivery: 'server',
    }
    default: throw new Error('语音服务返回了不支持的通话协议。')
  }
}
