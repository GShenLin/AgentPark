import { computed, onBeforeUnmount, ref } from 'vue'

function preferredAudioMimeType() {
  if (typeof MediaRecorder === 'undefined') return ''
  for (const value of ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/webm']) {
    if (MediaRecorder.isTypeSupported(value)) return value
  }
  return ''
}

async function encodeWav(blob: Blob) {
  const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
  if (!AudioContextClass) throw new Error('This browser cannot convert the recording to WAV.')
  const context: AudioContext = new AudioContextClass()
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer())
    const targetSampleRate = 16000
    let rendered = decoded
    if (decoded.sampleRate !== targetSampleRate) {
      const OfflineContextClass = window.OfflineAudioContext || (window as any).webkitOfflineAudioContext
      if (!OfflineContextClass) throw new Error('This browser cannot resample the recording to 16 kHz WAV.')
      const outputFrames = Math.max(1, Math.ceil(decoded.duration * targetSampleRate))
      const offline: OfflineAudioContext = new OfflineContextClass(1, outputFrames, targetSampleRate)
      const source = offline.createBufferSource()
      source.buffer = decoded
      source.connect(offline.destination)
      source.start()
      rendered = await offline.startRendering()
    }
    const frames = rendered.length
    const channels = rendered.numberOfChannels
    const output = new ArrayBuffer(44 + frames * 2)
    const view = new DataView(output)
    const writeText = (offset: number, text: string) => {
      for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index))
    }
    writeText(0, 'RIFF')
    view.setUint32(4, 36 + frames * 2, true)
    writeText(8, 'WAVE')
    writeText(12, 'fmt ')
    view.setUint32(16, 16, true)
    view.setUint16(20, 1, true)
    view.setUint16(22, 1, true)
    view.setUint32(24, rendered.sampleRate, true)
    view.setUint32(28, rendered.sampleRate * 2, true)
    view.setUint16(32, 2, true)
    view.setUint16(34, 16, true)
    writeText(36, 'data')
    view.setUint32(40, frames * 2, true)
    const sourceChannels = Array.from({ length: channels }, (_, index) => rendered.getChannelData(index))
    for (let frame = 0; frame < frames; frame += 1) {
      let sample = 0
      for (const source of sourceChannels) sample += source[frame] || 0
      sample = Math.max(-1, Math.min(1, sample / channels))
      view.setInt16(44 + frame * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true)
    }
    return new Blob([output], { type: 'audio/wav' })
  } finally {
    await context.close().catch(() => undefined)
  }
}

export function useAudioRecorder() {
  const recording = ref(false)
  const recorder = ref<MediaRecorder | null>(null)
  const stream = ref<MediaStream | null>(null)
  const chunks: Blob[] = []
  let stopResolve: ((file: File) => void) | null = null
  let stopReject: ((error: Error) => void) | null = null

  const supported = computed(() => (
    typeof navigator !== 'undefined'
    && !!navigator.mediaDevices?.getUserMedia
    && typeof MediaRecorder !== 'undefined'
  ))

  function releaseStream() {
    for (const track of stream.value?.getTracks() || []) track.stop()
    stream.value = null
  }

  async function start() {
    if (!supported.value) throw new Error('Audio recording is not supported by this browser.')
    if (recording.value) return
    const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mimeType = preferredAudioMimeType()
    const mediaRecorder = mimeType ? new MediaRecorder(mediaStream, { mimeType }) : new MediaRecorder(mediaStream)
    chunks.splice(0, chunks.length)
    mediaRecorder.addEventListener('dataavailable', (event) => {
      if (event.data.size > 0) chunks.push(event.data)
    })
    mediaRecorder.addEventListener('error', (event) => {
      const error = new Error((event as ErrorEvent).message || 'Audio recording failed.')
      stopReject?.(error)
      stopResolve = null
      stopReject = null
      recording.value = false
      releaseStream()
    })
    mediaRecorder.addEventListener('stop', async () => {
      const resolvedMime = mediaRecorder.mimeType || mimeType || 'audio/webm'
      const blob = new Blob(chunks, { type: resolvedMime })
      try {
        const wav = await encodeWav(blob)
        const file = new File(
          [wav],
          `recording-${new Date().toISOString().replace(/[:.]/g, '-')}.wav`,
          { type: 'audio/wav' },
        )
        stopResolve?.(file)
      } catch (error) {
        stopReject?.(error instanceof Error ? error : new Error(String(error)))
      }
      stopResolve = null
      stopReject = null
      recording.value = false
      recorder.value = null
      releaseStream()
    }, { once: true })
    stream.value = mediaStream
    recorder.value = mediaRecorder
    mediaRecorder.start(250)
    recording.value = true
  }

  async function stop(): Promise<File> {
    const current = recorder.value
    if (!current || current.state === 'inactive') throw new Error('Audio recording is not active.')
    return new Promise<File>((resolve, reject) => {
      stopResolve = resolve
      stopReject = reject
      current.stop()
    })
  }

  function dispose() {
    const current = recorder.value
    if (current && current.state !== 'inactive') current.stop()
    recording.value = false
    recorder.value = null
    stopResolve = null
    stopReject = null
    releaseStream()
  }

  onBeforeUnmount(dispose)
  return { recording, supported, start, stop, dispose }
}
