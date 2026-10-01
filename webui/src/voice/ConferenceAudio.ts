// Each outgoing stream is microphone + every remote speaker except its owner.
// Audio routing has no turn scheduler: participants can speak and work concurrently.
export class ConferenceAudio {
  private readonly context: AudioContext
  private microphone?: MediaStream
  private micSource?: MediaStreamAudioSourceNode
  private readonly inputs = new Map<string, MediaStreamAudioDestinationNode>()
  private readonly speakers = new Map<string, { source: MediaStreamAudioSourceNode; playback: GainNode }>()
  private closed = false

  constructor() { this.context = new AudioContext() }

  async open(onMicrophoneEnded: () => void) {
    // Resume synchronously from the start button's user gesture, including on mobile.
    const resume = this.context.resume()
    const capture = navigator.mediaDevices.getUserMedia({ audio: {
      echoCancellation: true, noiseSuppression: true, autoGainControl: true,
    } }).then(stream => {
      if (this.closed) { stream.getTracks().forEach(track => track.stop()); return }
      this.microphone = stream
      this.micSource = this.context.createMediaStreamSource(stream)
      stream.getAudioTracks().forEach(track => { track.onended = onMicrophoneEnded })
    })
    await Promise.all([resume, capture])
    if (this.closed) throw new Error('通话已结束。')
  }

  input(id: string): MediaStream {
    if (this.closed || !this.micSource) throw new Error('会议麦克风尚未就绪。')
    if (this.inputs.has(id)) throw new Error('节点已加入通话。')
    const destination = this.context.createMediaStreamDestination()
    this.inputs.set(id, destination)
    this.micSource.connect(destination)
    for (const [speaker, audio] of this.speakers) if (speaker !== id) audio.source.connect(destination)
    return destination.stream
  }

  receive(id: string, stream: MediaStream) {
    if (this.closed || !this.inputs.has(id)) throw new Error('节点已离开通话。')
    this.removeSpeaker(id)
    const source = this.context.createMediaStreamSource(stream)
    const playback = this.context.createGain()
    source.connect(playback).connect(this.context.destination)
    for (const [listener, destination] of this.inputs) if (listener !== id) source.connect(destination)
    this.speakers.set(id, { source, playback })
  }

  muteMicrophone(muted: boolean) {
    this.microphone?.getAudioTracks().forEach(track => { track.enabled = !muted })
  }

  mutePlayback(id: string, muted: boolean) {
    const speaker = this.speakers.get(id)
    if (speaker) speaker.playback.gain.value = muted ? 0 : 1
  }

  private removeSpeaker(id: string) {
    const speaker = this.speakers.get(id)
    if (!speaker) return
    speaker.source.disconnect(); speaker.playback.disconnect()
    this.speakers.delete(id)
  }

  leave(id: string) {
    this.removeSpeaker(id)
    const destination = this.inputs.get(id)
    if (!destination) return
    this.micSource?.disconnect(destination)
    for (const [speaker, audio] of this.speakers) if (speaker !== id) audio.source.disconnect(destination)
    destination.stream.getTracks().forEach(track => track.stop())
    destination.disconnect(); this.inputs.delete(id)
  }

  async close() {
    if (this.closed) return
    this.closed = true
    for (const id of [...this.inputs.keys()]) this.leave(id)
    this.micSource?.disconnect()
    this.microphone?.getTracks().forEach(track => { track.onended = null; track.stop() })
    await this.context.close()
  }
}
