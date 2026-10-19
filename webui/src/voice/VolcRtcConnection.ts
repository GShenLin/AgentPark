import VERTC, { AudioSourceType, ConnectionState, MediaType, RoomProfileType, RTCAutoPlayPolicy,
  StreamIndex, type IRTCEngine } from '@volcengine/rtc'
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
      catch (cause) { callbacks.event({ kind: 'warning', text: `本次火山语音消息未处理，通话继续：${String(cause)}` }) }
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
  close(): Promise<void> {
    if (this.closePromise) return this.closePromise
    this.closed = true; clearTimeout(this.pulse)
    this.closePromise = (async () => {
      // Callers observe connection/publish errors; teardown still waits for their
      // in-flight SDK operations so a late join cannot outlive destruction.
      await Promise.allSettled([this.connecting])
      try { await this.engine.leaveRoom() }
      finally { VERTC.destroyEngine(this.engine) }
    })()
    return this.closePromise
  }
}
