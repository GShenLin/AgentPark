// Local WebSocket RPC. HTTP requests remain owned by the Python curl transport.
class TrayChannel {
  constructor(target, onDisconnect, Socket = WebSocket) {
    this.pending = new Map()
    this.sequence = 0
    this.closed = false
    this.socket = new Socket(`${target.origin.replace('http:', 'ws:')}/api/desktop/tray`)
    this.ready = new Promise((resolve, reject) => {
      this.resolveReady = resolve
      this.rejectReady = reject
    })
    this.timer = setTimeout(() => this.fail(new Error('AgentPark tray connection timed out.')), 10000)
    this.socket.addEventListener('open', () => this.socket.send(JSON.stringify({ token: target.token })))
    this.socket.addEventListener('message', event => {
      try { this.receive(JSON.parse(event.data)) }
      catch (error) { this.fail(error) }
    })
    this.socket.addEventListener('error', () => this.fail(new Error('AgentPark tray connection failed.')))
    this.socket.addEventListener('close', () => {
      const intentional = this.closed
      this.dispose(new Error('AgentPark service disconnected.'))
      if (!intentional) onDisconnect()
    })
  }

  receive(message) {
    if (message.ready === true && Object.keys(message).length === 1) {
      clearTimeout(this.timer)
      this.resolveReady()
      return
    }
    if (typeof message.id !== 'string' || typeof message.ok !== 'boolean') throw new Error('Invalid tray response.')
    const pending = this.pending.get(message.id)
    if (!pending) throw new Error('Unexpected tray response ID.')
    this.pending.delete(message.id)
    clearTimeout(pending.timer)
    if (message.ok) pending.resolve(message.result)
    else if (typeof message.error === 'string') pending.reject(new Error(message.error))
    else pending.reject(new Error('Invalid tray error response.'))
  }

  async request(action, fields = {}) {
    await this.ready
    if (this.closed) throw new Error('AgentPark service disconnected.')
    const id = String(++this.sequence)
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`AgentPark tray command timed out: ${action}`))
      }, 40000)
      this.pending.set(id, { resolve, reject, timer })
      this.socket.send(JSON.stringify({ id, action, ...fields }))
    })
  }

  fail(error) {
    this.rejectReady(error)
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(error) }
    this.pending.clear()
    this.socket.close()
  }

  dispose(error = new Error('Tray closed.')) {
    this.closed = true
    clearTimeout(this.timer)
    this.fail(error)
  }
}

module.exports = { TrayChannel }
