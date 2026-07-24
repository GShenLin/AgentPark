type AudioStreamEvent = {
  type?: string
  stream_id?: string
  sequence?: number
  data?: string
  mime?: string
  format?: string
  sample_rate?: number
}

type StreamState = {
  id: string
  mime: string
  format: string
  sampleRate: number
  seen: Set<number>
  queue: Uint8Array[]
  audio?: HTMLAudioElement
  mediaSource?: MediaSource
  sourceBuffer?: SourceBuffer
  audioContext?: AudioContext
  nextPlaybackTime: number
  ended: boolean
}

const streams = new Map<string, StreamState>()

function decodeBase64(value: string) {
  const binary = atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return bytes
}

function finishMediaSource(state: StreamState) {
  if (!state.ended || state.queue.length || state.sourceBuffer?.updating) return
  if (state.mediaSource?.readyState === 'open') state.mediaSource.endOfStream()
}

function pumpMediaSource(state: StreamState) {
  if (!state.sourceBuffer || state.sourceBuffer.updating) return
  const next = state.queue.shift()
  if (!next) {
    finishMediaSource(state)
    return
  }
  const copy = new Uint8Array(next.byteLength)
  copy.set(next)
  state.sourceBuffer.appendBuffer(copy.buffer)
}

function startCompressedStream(state: StreamState) {
  if (typeof MediaSource === 'undefined' || !MediaSource.isTypeSupported(state.mime)) return
  const mediaSource = new MediaSource()
  const audio = new Audio()
  audio.autoplay = true
  audio.src = URL.createObjectURL(mediaSource)
  state.mediaSource = mediaSource
  state.audio = audio
  mediaSource.addEventListener('sourceopen', () => {
    if (mediaSource.readyState !== 'open') return
    const buffer = mediaSource.addSourceBuffer(state.mime)
    state.sourceBuffer = buffer
    buffer.addEventListener('updateend', () => pumpMediaSource(state))
    pumpMediaSource(state)
  }, { once: true })
  void audio.play().catch(() => undefined)
}

function playPcmChunk(state: StreamState, bytes: Uint8Array) {
  const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
  if (!AudioContextClass || bytes.byteLength < 2) return
  const context: AudioContext = state.audioContext || new AudioContextClass()
  state.audioContext = context
  void context.resume().catch(() => undefined)
  const sampleCount = Math.floor(bytes.byteLength / 2)
  const buffer = context.createBuffer(1, sampleCount, state.sampleRate)
  const channel = buffer.getChannelData(0)
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  for (let index = 0; index < sampleCount; index += 1) channel[index] = view.getInt16(index * 2, true) / 32768
  const source = context.createBufferSource()
  source.buffer = buffer
  source.connect(context.destination)
  const startAt = Math.max(context.currentTime, state.nextPlaybackTime)
  source.start(startAt)
  state.nextPlaybackTime = startAt + buffer.duration
}

function startStream(event: AudioStreamEvent) {
  const id = String(event.stream_id || '').trim()
  if (!id || streams.has(id)) return
  const state: StreamState = {
    id,
    mime: String(event.mime || 'audio/mpeg'),
    format: String(event.format || 'mp3'),
    sampleRate: Number(event.sample_rate || 24000),
    seen: new Set<number>(),
    queue: [],
    nextPlaybackTime: 0,
    ended: false,
  }
  streams.set(id, state)
  if (state.format !== 'pcm') startCompressedStream(state)
}

function consumeChunk(event: AudioStreamEvent) {
  const state = streams.get(String(event.stream_id || '').trim())
  const sequence = Number(event.sequence)
  if (!state || !Number.isInteger(sequence) || state.seen.has(sequence) || !event.data) return
  state.seen.add(sequence)
  const bytes = decodeBase64(event.data)
  if (state.format === 'pcm') playPcmChunk(state, bytes)
  else {
    state.queue.push(bytes)
    pumpMediaSource(state)
  }
}

function endStream(event: AudioStreamEvent) {
  const state = streams.get(String(event.stream_id || '').trim())
  if (!state) return
  state.ended = true
  finishMediaSource(state)
}

export function consumeAudioStreamEvents(value: unknown) {
  if (!Array.isArray(value)) return
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') continue
    const event = raw as AudioStreamEvent
    const type = String(event.type || '').trim().toLowerCase()
    if (type === 'audio_stream_start') startStream(event)
    else if (type === 'audio_stream_chunk') consumeChunk(event)
    else if (type === 'audio_stream_end') endStream(event)
  }
}
