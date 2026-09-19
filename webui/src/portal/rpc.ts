export interface HttpReply { status: number; headers: Record<string, string>; body: string }
interface Pending { resolve: (result: HttpReply) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }
const MAX_MESSAGE = 8 * 1024 * 1024
const FRAME_SIZE = 16000

export class BrowserPeerRpc {
  private pending = new Map<string, Pending>()
  private writeTail: Promise<void> = Promise.resolve()
  private message: Uint8Array | null = null
  private position = 0
  private closed = false
  private waiting: (() => void)[] = []
  private active = 0
  private channel: RTCDataChannel

  constructor(channel: RTCDataChannel) {
    this.channel = channel
    channel.binaryType = 'arraybuffer'
    channel.addEventListener('message', event => this.receive(event.data))
    channel.addEventListener('close', () => this.close())
  }
  close() {
    if (this.closed) return
    this.closed = true
    for (const request of this.pending.values()) { clearTimeout(request.timer); request.reject(new Error('Device disconnected. Request outcome may be unknown.')) }
    this.pending.clear(); this.message = null
    for (const wake of this.waiting.splice(0)) wake()
  }
  private receive(raw: unknown) {
    try {
      if (!(raw instanceof ArrayBuffer) || raw.byteLength > FRAME_SIZE) throw new Error('Invalid data frame.')
      let bytes = new Uint8Array(raw)
      if (!this.message) {
        if (bytes.length < 4) throw new Error('Missing frame length.')
        const size = new DataView(raw).getUint32(0)
        if (!size || size > MAX_MESSAGE) throw new Error('Invalid message size.')
        this.message = new Uint8Array(size); this.position = 0; bytes = bytes.subarray(4)
      }
      if (this.position + bytes.length > this.message.length) throw new Error('Unexpected message boundary.')
      this.message.set(bytes, this.position); this.position += bytes.length
      if (this.position !== this.message.length) return
      const body = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(this.message))
      this.message = null
      if (body.kind !== 'response' || body.version !== 1 || typeof body.ok !== 'boolean') throw new Error('Invalid RPC response.')
      const pending = this.pending.get(body.request_id)
      if (!pending) return
      if (!body.ok) { this.pending.delete(body.request_id); clearTimeout(pending.timer); pending.reject(new Error(String(body.error))); return }
      const result = body.result
      if (!result || !Number.isInteger(result.status) || result.status < 100 || result.status > 599 || typeof result.body !== 'string' || !result.headers || typeof result.headers !== 'object') throw new Error('Invalid Board HTTP response.')
      this.pending.delete(body.request_id); clearTimeout(pending.timer)
      pending.resolve(result)
    } catch (cause) { this.channel.close(); this.close(); console.error('Board transport protocol error', cause) }
  }
  private async send(body: unknown) {
    const data = new TextEncoder().encode(JSON.stringify(body))
    if (data.length > MAX_MESSAGE) throw new Error('Board request is larger than 8 MiB.')
    const payload = new Uint8Array(data.length + 4)
    new DataView(payload.buffer).setUint32(0, data.length); payload.set(data, 4)
    for (let offset = 0; offset < payload.length; offset += FRAME_SIZE) {
      const deadline = Date.now() + 10000
      while (this.channel.bufferedAmount > 256000) {
        if (this.closed || Date.now() > deadline) throw new Error('Board send buffer timed out.')
        await new Promise(resolve => setTimeout(resolve, 10))
      }
      if (this.channel.readyState !== 'open') throw new Error('Board is not connected.')
      this.channel.send(payload.subarray(offset, offset + FRAME_SIZE))
    }
  }
  async http(request: Record<string, unknown>): Promise<HttpReply> {
    while (this.active >= 6 && !this.closed) await new Promise<void>(resolve => this.waiting.push(resolve))
    if (this.closed) throw new Error('Board connection is closed.')
    this.active++
    const requestId = crypto.randomUUID().replace(/-/g, '')
    try {
      return await new Promise<HttpReply>((resolve, reject) => {
        const timer = setTimeout(() => { this.pending.delete(requestId); reject(new Error('Board request timed out; no automatic replay.')) }, 45000)
        this.pending.set(requestId, { resolve, reject, timer })
        const send = this.writeTail.then(() => this.send({ version: 1, kind: 'request', request_id: requestId, call: { operation: 'board_http', http: request } }))
        this.writeTail = send.catch(() => {})
        send.catch(cause => {
          const pending = this.pending.get(requestId)
          if (pending) { clearTimeout(pending.timer); this.pending.delete(requestId); pending.reject(cause instanceof Error ? cause : new Error(String(cause))) }
        })
      })
    } finally { this.active--; this.waiting.shift()?.() }
  }
}
