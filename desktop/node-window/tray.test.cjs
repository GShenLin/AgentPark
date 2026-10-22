const { test } = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { trayMenu } = require('./tray-menu.cjs')
const { TrayChannel } = require('./tray-channel.cjs')
const { parseHostLaunch, forwardedLaunch } = require('./contract.cjs')

test('tray launches and forwarded launches validate local origin and capability', () => {
  const args = ['--tray', '--origin=http://127.0.0.1:8788', `--token=${'a'.repeat(64)}`]
  const target = parseHostLaunch(args)
  assert.deepEqual(forwardedLaunch(target), target)
  assert.throws(() => parseHostLaunch(args.slice(0, 2)))
  assert.throws(() => forwardedLaunch({ ...target, origin: 'https://evil.example' }))
})

const node = { graph_id: '画布', node_id: 'n', name: 'A&B', state: 'working', saved_at_ns: 123 }
test('Working and Recent have independent node identities and actions', () => {
  const calls = []
  const menu = trayMenu({ recent: [node], working: [{ ...node, graph_id: 'other' }] }, {
    openNode: item => calls.push(item), newNode: () => calls.push('new'),
  })
  const items = menu.filter(item => item.label?.startsWith('  A&&B'))
  assert.equal(items.length, 2)
  items.forEach(item => item.click())
  assert.deepEqual(calls.map(item => item.graph_id), ['other', '画布'])
  menu.find(item => item.label?.startsWith('NewNode')).click()
  assert.equal(calls.at(-1), 'new')
  assert.throws(() => trayMenu({ recent: [null], working: [] }, {}))
})

class Socket extends EventEmitter {
  constructor(url) { super(); this.url = url; this.sent = []; Socket.last = this }
  addEventListener(event, handler) { this.on(event, handler) }
  send(message) { this.sent.push(JSON.parse(message)) }
  close() { if (!this.closed) { this.closed = true; this.emit('close') } }
  receive(message) { this.emit('message', { data: JSON.stringify(message) }) }
}

test('channel authenticates before requests, correlates results and disposes pending commands', async () => {
  let disconnected = 0
  const channel = new TrayChannel({ origin: 'http://127.0.0.1:8788', token: 'secret' }, () => disconnected++, Socket)
  const socket = Socket.last
  assert.ok(!socket.url.includes('secret'))
  socket.emit('open')
  assert.deepEqual(socket.sent, [{ token: 'secret' }])
  socket.receive({ ready: true })
  const first = channel.request('snapshot')
  const second = channel.request('open-node', { graph_id: 'g', node_id: 'n' })
  await Promise.resolve()
  socket.receive({ id: '2', ok: false, error: 'Node deleted' })
  socket.receive({ id: '1', ok: true, result: { recent: [], working: [] } })
  assert.deepEqual(await first, { recent: [], working: [] })
  await assert.rejects(second, /Node deleted/)
  const pending = channel.request('exit')
  await Promise.resolve()
  channel.dispose()
  await assert.rejects(pending, /Tray closed/)
  assert.equal(disconnected, 0)
  await assert.rejects(channel.request('snapshot'), /disconnected/)
})

test('server disconnect releases tray lifecycle instead of keeping a stale icon', async () => {
  let disconnected = 0
  const channel = new TrayChannel({ origin: 'http://127.0.0.1:8788', token: 'secret' }, () => disconnected++, Socket)
  Socket.last.receive({ ready: true })
  await channel.ready
  Socket.last.close()
  assert.equal(disconnected, 1)
})
