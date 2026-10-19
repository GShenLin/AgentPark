import { ref, watch, type Ref } from 'vue'
import { voiceRequest, type VoiceTarget } from '../voiceApi'
import type { AnnotationDrawing } from './screenAnnotations'

type DesktopSession = { target: VoiceTarget; session: string }

/** Pixels travel from the execution host to the model; this page receives only metadata. */
export function useVoiceDesktopTools(session: () => DesktopSession, connected: Ref<boolean>) {
  const drawn = ref(false), error = ref('')
  async function request(path: string, payload: object) {
    const owner = session()
    const result = await voiceRequest(owner.target, `/${encodeURIComponent(owner.session)}/${path}`, {
      method: 'POST', body: JSON.stringify(payload), signal: AbortSignal.timeout(45000),
    })
    if (result?.ok !== true) throw new Error('执行设备未确认操作成功。')
    return result
  }
  async function capture(id: string, displayId: string) {
    const result = await request('screenshot', { request_id: id, display_id: displayId })
    if (result.delivered !== true || typeof result.frame_id !== 'string' || !result.frame_id
        || typeof result.width !== 'number' || typeof result.height !== 'number') throw new Error('截图未确认送达语音模型。')
    return JSON.stringify(result)
  }
  async function draw(drawing: AnnotationDrawing) {
    await request('annotations', drawing)
    drawn.value = drawing.action !== 'clear'
    error.value = ''
    return drawing.action === 'clear' ? '桌面标注已清除。' : '已在执行设备上绘制标注。'
  }
  async function clear() {
    try { await draw({ action: 'clear', frame_id: '', duration_seconds: 1, shapes: [] }) }
    catch (cause) { error.value = `清除标注失败：${cause instanceof Error ? cause.message : String(cause)}` }
  }
  watch(connected, value => { if (!value) { drawn.value = false; error.value = '' } })
  return { capture, draw, clear, drawn, error }
}
