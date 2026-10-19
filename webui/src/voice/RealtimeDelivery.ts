type Item = { id?: string; type: string; [key: string]: unknown }
type Pending = { item: Item; sentAt?: number; probe?: string; resolve: () => void; reject: (error: Error) => void }

/** Retain content until the provider confirms insertion. A lost acknowledgement is
 * reconciled by retrieving the same item, never by blindly adding a duplicate. */
export class RealtimeDelivery {
  private pending = new Map<string, Pending>()
  private deliveries = new Map<string, Promise<void>>()
  available = true
  private send: (event: object) => void
  private now: () => number
  constructor(send: (event: object) => void, now: () => number) { this.send = send; this.now = now }

  enqueue(key: string, items: Item[]): Promise<void> {
    const existing = this.deliveries.get(key)
    if (existing) return existing
    const promises = items.map(item => new Promise<void>((resolve, reject) => {
      const id = `ctx_${crypto.randomUUID().replace(/-/g, '').slice(0, 24)}`
      this.pending.set(id, { item: { ...item, id }, resolve, reject })
    }))
    const done = Promise.all(promises).then(() => undefined)
    // Task updates may be queued without a waiter; errors are also surfaced by parse.
    void done.catch(() => {})
    this.deliveries.set(key, done)
    this.flush()
    return done
  }

  acknowledge(id: string) {
    const pending = this.pending.get(id)
    if (pending) { this.pending.delete(id); pending.resolve() }
  }

  flush() {
    if (!this.available) return
    for (const [id, pending] of this.pending) {
      if (pending.sentAt === undefined) {
        this.send({ type: 'conversation.item.create', event_id: `create_${id}`, item: pending.item })
        pending.sentAt = this.now()
      } else if (this.now() - pending.sentAt >= 10000) {
        const probe = `probe_${id}`
        this.send({ type: 'conversation.item.retrieve', item_id: id, event_id: probe })
        pending.probe = probe; pending.sentAt = this.now()
      }
    }
  }

  error(event: { event_id?: string; code?: string; message?: string }): { kind: 'handled' } | { kind: 'failed'; text: string } | undefined {
    if (!event.event_id) return
    const match = [...this.pending].find(([id, item]) => item.probe === event.event_id || `create_${id}` === event.event_id)
    if (!match) return
    const [id, pending] = match
    // Only an explicit missing-item result authorizes resending the original item.
    if (pending.probe === event.event_id && event.code === 'item_retrieve_invalid_item_id') {
      pending.sentAt = undefined; pending.probe = undefined; return { kind: 'handled' }
    }
    const text = `本次消息未送达语音服务，通话继续：${event.message || event.code || '服务拒绝了消息'}`
    this.pending.delete(id); pending.reject(new Error(text))
    return { kind: 'failed', text }
  }

  close() {
    for (const item of this.pending.values()) item.reject(new Error('语音通话已结束，消息尚未确认送达。'))
    this.pending.clear(); this.deliveries.clear()
  }
}
