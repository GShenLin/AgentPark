import { voiceRequest, type VoiceTarget } from '../voiceApi'
import type { VoiceProtocolAdapter } from './voiceProtocol'

/** Tool execution is shared; only delivery to the voice model varies by transport. */
export async function deliverVoiceToolResult(options: {
  target: VoiceTarget; session: string; protocol: VoiceProtocolAdapter; signal: AbortSignal
}, id: string, result: { status: 'completed' | 'failed'; text: string; image_frame_id?: string }) {
  options.signal.throwIfAborted()
  if (options.protocol.resultDelivery === 'data-channel') {
    options.protocol.dialogue.taskUpdate(id, result)
    return
  }
  const response = await voiceRequest(options.target, `/${encodeURIComponent(options.session)}/tools/${encodeURIComponent(id)}/result`, {
    method: 'POST', body: JSON.stringify(result), signal: options.signal,
  })
  if (!['accepted', 'duplicate'].includes(response?.delivery)) throw new Error('工具结果尚未送达语音模型。')
}
