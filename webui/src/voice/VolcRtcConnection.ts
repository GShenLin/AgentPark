import VERTC, { AudioSourceType, ConnectionState, MediaType, RoomProfileType, RTCAutoPlayPolicy,
  StreamIndex, VideoSourceType, type IRTCEngine } from '@volcengine/rtc'
import { controlRtcCall, type RtcConnection, type VoiceTarget } from '../voiceApi'
import type { VoiceEvent } from './voiceProtocol'
import { VolcRtcEvents } from './VolcRtcEvents'

type Callbacks = { event: (event: VoiceEvent) => void; audio: (stream: MediaStream) => void; error: (message: string) => void }

/** RTC owns media; the node API alone owns tools, credentials and AI task lifetime. */
export class VolcRtcConnection {
  private engine: IRTCEngine
  private target: VoiceTarget
  private session: string
  private info: RtcConnection
  private callbacks: Callbacks
  private closed = false
  private pulse?: ReturnType<typeof setTimeout>
  private screenTrack?: MediaStreamTrack
  private screenQueue: Promise<void> = Promise.resolve()
  private fps = 0
  private statsAt = 0
  private activated = false
  private subscribed = false
  private announced = false
  private closePromise?: Promise<void>
  private connecting?: Promise<void>
  private signal: AbortSignal

  constructor(target: VoiceTarget, session: string, info: RtcConnection, signal: AbortSignal, callbacks: Callbacks) {
    this.target = target; this.session = session; this.info = info; this.callbacks = callbacks; this.signal = signal
    this.engine = VERTC.createEngine(info.app_id, { autoPlayPolicy: RTCAutoPlayPolicy.PLAY_MANUALLY })
    const parser = new VolcRtcEvents(info.user_id, info.bot_id)
    this.engine.on(VERTC.events.onError, event => this.report(`火山 RTC 错误：${event.errorCode}`))
    this.engine.on(VERTC.events.onConnectionStateChanged, event => {
      if (event.state === ConnectionState.CONNECTION_STATE_LOST) this.report('火山 RTC 连接中断，重连未成功。')
    })
    this.engine.on(VERTC.events.onUserLeave, event => {
      if (event.userInfo.userId === info.bot_id) this.report('火山语音智能体已离开通话。')
    })
    this.engine.on(VERTC.events.onUserPublishStream, event => {
      if (event.userId === info.bot_id && event.mediaType !== MediaType.VIDEO) {
        void this.subscribe().catch(cause => this.report(String(cause)))
      }
    })
    this.engine.on(VERTC.events.onRoomBinaryMessageReceived, event => {
      if (this.closed || event.userId !== info.bot_id) return
      try { for (const parsed of parser.parse(event.message)) callbacks.event(parsed) }
      catch (cause) { this.report(String(cause)) }
    })
    this.engine.on(VERTC.events.onLocalStreamStats, stats => {
      if (stats.isScreen) { this.fps = stats.videoStats.sentFrameRate; this.statsAt = performance.now() }
    })
  }

  private report(message: string) { if (!this.closed) this.callbacks.error(message) }
  private check() { if (this.closed || this.signal.aborted) throw new Error('通话已经结束。') }
  private ready() {
    if (!this.closed && this.activated && this.subscribed && !this.announced) {
      this.announced = true; this.callbacks.event({ kind: 'ready' })
    }
  }
  private async subscribe() {
    await this.engine.subscribeStream(this.info.bot_id, MediaType.AUDIO)
    if (this.closed) return
    const track = this.engine.getRemoteStreamTrack(this.info.bot_id, StreamIndex.STREAM_INDEX_MAIN, 'audio')
    if (!track) throw new Error('火山 RTC 已订阅，但未返回音频轨道。')
    this.callbacks.audio(new MediaStream([track]))
    this.subscribed = true; this.ready()
  }
  connect(stream: MediaStream): Promise<void> {
    if (this.connecting) throw new Error('火山通话已在连接中。')
    this.connecting = this.open(stream)
    return this.connecting
  }
  private async open(stream: MediaStream) {
    const track = stream.getAudioTracks()[0]
    if (!track) throw new Error('没有可发送的麦克风音轨。')
    this.check()
    await this.engine.setAudioSourceType(StreamIndex.STREAM_INDEX_MAIN, AudioSourceType.AUDIO_SOURCE_TYPE_EXTERNAL)
    this.check()
    await this.engine.setExternalAudioTrack(StreamIndex.STREAM_INDEX_MAIN, track)
    this.check()
    await this.engine.joinRoom(this.info.token, this.info.room_id, { userId: this.info.user_id }, {
      roomProfileType: RoomProfileType.chat, isAutoPublish: false, isAutoSubscribeAudio: false, isAutoSubscribeVideo: false,
    })
    this.check()
    await this.engine.publishStream(MediaType.AUDIO)
    this.check()
    await controlRtcCall(this.target, this.session, { action: 'activate' }, this.signal)
    this.check(); this.activated = true; this.ready(); this.heartbeat()
  }
  private heartbeat() {
    this.pulse = setTimeout(() => {
      if (this.closed) return
      void controlRtcCall(this.target, this.session, { action: 'heartbeat' }, this.signal)
        .then(() => { if (!this.closed) this.heartbeat() }).catch(cause => this.report(`通话保活失败：${String(cause)}`))
    }, 15000)
  }
  screen(stream: MediaStream | null, fps: number): Promise<void> {
    const operation = this.screenQueue.then(() => this.setScreen(stream, fps))
    // Preserve sequencing after a failed operation; its caller receives the rejection.
    this.screenQueue = operation.catch(() => {})
    return operation
  }
  private async setScreen(stream: MediaStream | null, fps: number) {
    this.check()
    if (!Number.isInteger(fps) || fps < 1 || fps > 30) throw new Error('共享帧率须为 1–30 之间的整数。')
    if (stream) {
      const source = stream.getVideoTracks()[0]
      if (!source || source.readyState === 'ended') throw new Error('共享画面已结束。')
      const index = StreamIndex.STREAM_INDEX_SCREEN
      await this.engine.setScreenEncoderConfig({ width: 1920, height: 1080, frameRate: fps, maxKbps: 4000, contentHint: 'detail' })
      this.check()
      if (!this.screenTrack) {
        // Each call owns a clone; leaving one participant cannot stop the shared capture.
        this.screenTrack = source.clone()
        await this.engine.setVideoSourceType(index, VideoSourceType.VIDEO_SOURCE_TYPE_EXTERNAL)
        this.check()
        await this.engine.setExternalVideoTrack(index, this.screenTrack)
        this.check()
        await this.engine.publishScreen(MediaType.VIDEO)
      }
      this.check()
      await controlRtcCall(this.target, this.session, { action: 'screen', enabled: true, fps }, this.signal)
    } else {
      if (this.screenTrack) {
        try { await this.engine.unpublishScreen(MediaType.VIDEO) }
        finally { this.screenTrack.stop(); this.screenTrack = undefined; this.fps = 0 }
      }
      this.fps = 0
      await controlRtcCall(this.target, this.session, { action: 'screen', enabled: false, fps }, this.signal)
    }
  }
  screenFps() { return this.screenTrack && performance.now() - this.statsAt < 5000 ? this.fps : 0 }
  close(): Promise<void> {
    if (this.closePromise) return this.closePromise
    this.closed = true; clearTimeout(this.pulse)
    this.screenTrack?.stop()
    this.closePromise = (async () => {
      // Callers observe connection/publish errors; teardown still waits for their
      // in-flight SDK operations so a late join cannot outlive destruction.
      await Promise.allSettled([this.connecting, this.screenQueue])
      try { await this.engine.leaveRoom() }
      finally { this.screenTrack?.stop(); VERTC.destroyEngine(this.engine) }
    })()
    return this.closePromise
  }
}
