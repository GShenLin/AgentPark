type CandidateUpdate = {
  kind: 'ice_candidate'; sequence: number; candidate: string | null
  sdp_mid: string | null; sdp_mline_index: number | null
}
type OfferUpdate = { kind: 'offer'; sdp: string }

/** Trickle ICE: send the offer immediately, then signed candidates in discovery order. */
export class BoardOffer {
  private ready = false
  private closed = false
  private started = false
  private sequence = 0
  private pending: CandidateUpdate[] = []
  private queue: Promise<void> = Promise.resolve()
  private counts = new Map<string, number>()
  private errors = new Set<number>()

  private pc: RTCPeerConnection
  private send: (packet: OfferUpdate | CandidateUpdate) => Promise<void>
  private fail: (error: Error) => void

  constructor(pc: RTCPeerConnection,
    send: (packet: OfferUpdate | CandidateUpdate) => Promise<void>,
    fail: (error: Error) => void) {
    this.pc = pc; this.send = send; this.fail = fail
    pc.addEventListener('icecandidate', this.candidate)
    pc.addEventListener('icecandidateerror', this.candidateError)
  }

  private candidateError = (event: RTCPeerConnectionIceErrorEvent) => { this.errors.add(event.errorCode) }
  private candidate = (event: RTCPeerConnectionIceEvent) => {
    if (this.closed) return
    const value = event.candidate
    // An empty candidate string ends one media section; null ends the generation.
    if (value && !value.candidate) return
    if (this.sequence > 128 || (value && this.sequence === 128)) {
      this.fail(new Error('浏览器产生的网络连接地址过多，请检查虚拟网卡配置。')); return
    }
    if (value) this.counts.set(value.type || 'unknown', (this.counts.get(value.type || 'unknown') || 0) + 1)
    const update: CandidateUpdate = { kind: 'ice_candidate', sequence: this.sequence++,
      candidate: value?.candidate ?? null, sdp_mid: value?.sdpMid ?? null,
      sdp_mline_index: value?.sdpMLineIndex ?? null }
    if (!this.ready) this.pending.push(update)
    else this.enqueue(update)
  }

  private enqueue(update: CandidateUpdate) {
    this.queue = this.queue.then(async () => { if (!this.closed) await this.send(update) })
      .catch(cause => { this.close(); this.fail(cause instanceof Error ? cause : new Error(String(cause))) })
  }

  async start() {
    if (this.started) throw new Error('Board 会话重复初始化。')
    this.started = true
    const offer = await this.pc.createOffer()
    if (this.closed) return
    if (!offer.sdp) throw new Error('浏览器未生成设备连接信息。')
    await this.pc.setLocalDescription(offer)
    if (this.closed) return
    // Keep candidates out of the initial snapshot: each is delivered once via its event.
    await this.send({ kind: 'offer', sdp: offer.sdp })
    if (this.closed) return
    this.ready = true
    for (const update of this.pending) this.enqueue(update)
    this.pending = []
  }

  diagnostic() {
    const types = [...this.counts].map(([type, count]) => `${type}=${count}`).join('，') || '未发现地址'
    return `地址收集 ${this.pc.iceGatheringState}；${types}${this.errors.size ? `；探测错误码 ${[...this.errors].join('/')}` : ''}`
  }

  close() {
    this.closed = true; this.pending = []
    this.pc.removeEventListener('icecandidate', this.candidate)
    this.pc.removeEventListener('icecandidateerror', this.candidateError)
  }
}
