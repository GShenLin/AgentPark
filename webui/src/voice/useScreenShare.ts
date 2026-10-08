import { computed, onBeforeUnmount, ref, shallowRef } from 'vue'

export const SCREEN_FPS_MIN = 1, SCREEN_FPS_MAX = 30
export type ScreenReceiver = { name: string } & (
  { kind: 'frames'; frame: (url: string) => boolean; stop: () => void; limit: () => number }
  | { kind: 'rtc'; stream: (stream: MediaStream | null, fps: number) => Promise<void>; fps: () => number })
/** One user-selected display stream for a room. Frames go directly to vision-capable calls. */
export function useScreenShare() {
  const stream = shallowRef<MediaStream | null>(null), video = shallowRef<HTMLVideoElement | null>(null)
  const pending = ref(false), error = ref(''), label = ref(''), sent = ref(0)
  const frameRate = ref(5), changingRate = ref(false)
  const rates = ref<{ id: number; name: string; fps: number }[]>([])
  const recentSends = new Map<number, number[]>()
  const receivers = shallowRef(new Map<number, ScreenReceiver>())
  const available = computed(() => receivers.value.size > 0)
  const names = computed(() => [...receivers.value.values()].map(r => r.name).join('、'))
  const hasRtc = computed(() => [...receivers.value.values()].some(r => r.kind === 'rtc'))
  const supported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getDisplayMedia
  let generation = 0, timer: ReturnType<typeof setTimeout> | undefined
  const used = new Set<number>()

  function detach(receiver: ScreenReceiver) {
    try {
      if (receiver.kind === 'frames') receiver.stop()
      else void receiver.stream(null, frameRate.value).catch(cause => { error.value = `停止画面发送失败：${String(cause)}` })
    } catch (cause) { error.value = `停止画面发送失败：${String(cause)}` }
  }

  async function attach(id: number, receiver: ScreenReceiver) {
    if (receiver.kind !== 'rtc' || !stream.value) return
    used.add(id)
    await receiver.stream(stream.value, frameRate.value)
  }

  function stop() {
    generation++; pending.value = false; clearTimeout(timer)
    stream.value?.getTracks().forEach(track => track.stop()); stream.value = null
    if (video.value) { video.value.pause(); video.value.srcObject = null }; video.value = null
    for (const id of used) {
      const receiver = receivers.value.get(id)
      if (receiver) detach(receiver)
    }
    used.clear(); recentSends.clear(); rates.value = []; label.value = ''; sent.value = 0
  }

  function register(id: number, receiver: ScreenReceiver | null) {
    const previous = receivers.value.get(id)
    if (previous && previous !== receiver && used.has(id)) { detach(previous); used.delete(id) }
    const next = new Map(receivers.value)
    if (receiver) next.set(id, receiver); else next.delete(id)
    if (!receiver) recentSends.delete(id)
    receivers.value = next
    if (receiver && stream.value) void attach(id, receiver).catch(cause => { error.value = String(cause); stop() })
    if (!next.size && (stream.value || pending.value)) stop()
  }

  async function frame(epoch: number) {
    if (epoch !== generation || !stream.value || !video.value) return
    const started = performance.now()
    try {
      const source = video.value
      const frameReceivers = [...receivers.value].filter((entry): entry is [number, Extract<ScreenReceiver, { kind: 'frames' }>] => entry[1].kind === 'frames')
      if (frameReceivers.length && source.readyState >= 2 && source.videoWidth && source.videoHeight) {
        const canvas = document.createElement('canvas')
        const scale = Math.min(1, 1600 / Math.max(source.videoWidth, source.videoHeight))
        canvas.width = Math.max(1, Math.round(source.videoWidth * scale)); canvas.height = Math.max(1, Math.round(source.videoHeight * scale))
        const context = canvas.getContext('2d')
        if (!context) throw new Error('浏览器无法读取共享画面。')
        context.drawImage(source, 0, 0, canvas.width, canvas.height)
        const limit = Math.min(...frameReceivers.map(([, r]) => r.limit())) - 1024
        // Explicit bandwidth budget: adapt JPEG quality to the negotiated SCTP limit.
        let url = ''
        for (const quality of [0.8, 0.6, 0.4, 0.2]) {
          url = canvas.toDataURL('image/jpeg', quality)
          if (url.length <= limit) break
        }
        if (!url.startsWith('data:image/jpeg;') || url.length > limit) throw new Error('共享画面超出当前连接的传输大小，请选择较小的窗口。')
        for (const [id, receiver] of frameReceivers) {
          if (receiver.frame(url)) {
            used.add(id); sent.value++
            const times = recentSends.get(id) || []; times.push(performance.now()); recentSends.set(id, times)
          }
        }
      }
      const cutoff = performance.now() - 2000
      rates.value = [...receivers.value].map(([id, receiver]) => {
        if (receiver.kind === 'rtc') return { id, name: receiver.name, fps: receiver.fps() }
        const times = (recentSends.get(id) || []).filter(at => at > cutoff); recentSends.set(id, times)
        return { id, name: receiver.name, fps: times.length / 2 }
      })
      // Compensate for encoding time, without overlapping captures or catch-up bursts.
      if (epoch === generation) timer = setTimeout(() => void frame(epoch), Math.max(0, 1000 / frameRate.value - (performance.now() - started)))
    } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause); stop() }
  }

  async function setFrameRate(value: number) {
    if (!Number.isInteger(value) || value < SCREEN_FPS_MIN || value > SCREEN_FPS_MAX) {
      error.value = `共享帧率须为 ${SCREEN_FPS_MIN}–${SCREEN_FPS_MAX} 之间的整数。`; return
    }
    if (changingRate.value) return
    const epoch = generation, track = stream.value?.getVideoTracks()[0]
    let captureChanged = false
    changingRate.value = true; error.value = ''
    try {
      if (track) await track.applyConstraints({ frameRate: { ideal: value, max: value } })
      captureChanged = true
      if (epoch !== generation) return
      frameRate.value = value
      for (const [id, receiver] of receivers.value) await attach(id, receiver)
      if (stream.value) { clearTimeout(timer); await frame(epoch) }
    } catch (cause) { if (epoch === generation) { error.value = `无法调整共享帧率：${String(cause)}`; if (captureChanged) stop() } }
    finally { changingRate.value = false }
  }

  async function start() {
    if (pending.value || stream.value) return
    error.value = ''
    if (!supported) { error.value = '当前浏览器不支持屏幕共享，请使用桌面浏览器，通过 HTTPS 或 localhost 打开。'; return }
    if (!available.value) { error.value = '当前没有支持屏幕共享的已接通节点。'; return }
    const epoch = ++generation; pending.value = true
    try {
      const selected = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: { ideal: frameRate.value, max: frameRate.value } }, audio: false })
      if (epoch !== generation) { selected.getTracks().forEach(track => track.stop()); return }
      stream.value = selected
      const track = selected.getVideoTracks()[0]
      if (!track) throw new Error('没有取得共享画面。')
      track.onended = () => { if (epoch === generation) stop() }
      track.onmute = () => { if (epoch === generation) { error.value = '共享画面已暂停或不可用，请重新选择窗口。'; stop() } }
      label.value = track.label || '所选屏幕'
      const element = document.createElement('video'); element.muted = true; element.playsInline = true
      element.srcObject = selected; video.value = element
      await element.play()
      if (epoch === generation) for (const [id, receiver] of receivers.value) {
        await attach(id, receiver)
        if (epoch !== generation) return
      }
      if (epoch === generation) { pending.value = false; await frame(epoch) }
    } catch (cause) {
      if (epoch !== generation) return
      error.value = cause instanceof DOMException && cause.name === 'NotAllowedError' ? '未开启共享：你取消了选择，或浏览器未获授权。' : String(cause)
      stop()
    }
  }

  onBeforeUnmount(stop)
  return { stream, pending, error, label, sent, available, names, supported, start, stop, register,
    frameRate, changingRate, rates, setFrameRate, hasRtc }
}

export type ScreenShare = ReturnType<typeof useScreenShare>
