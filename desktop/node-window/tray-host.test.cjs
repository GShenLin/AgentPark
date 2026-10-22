const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const { EventEmitter } = require('node:events')
const tick = () => new Promise(resolve => setImmediate(resolve))

test('native menu refreshes on each right-click and delegates NewNode, node focus and exit', async () => {
  let tray, current = { recent: [], working: [] }
  const requests = [], urls = [], errors = [], exports = { exports: {} }
  class FakeTray extends EventEmitter {
    constructor(icon) { super(); assert.equal(icon.byteLength, 32 * 32 * 4); tray = this }
    setToolTip(value) { this.tooltip = value }
    popUpContextMenu(menu) { this.menu = menu }
    destroy() { this.destroyed = true }
  }
  class Channel {
    ready = Promise.resolve()
    request(action, fields) { requests.push({ action, fields }); return Promise.resolve(action === 'snapshot' ? current : { ok: true }) }
    dispose() { this.closed = true }
  }
  vm.runInNewContext(fs.readFileSync(require.resolve('./tray-host.cjs'), 'utf8'), {
    Buffer, console, module: exports,
    require: id => {
      if (id === 'electron') return {
        Tray: FakeTray, Menu: { buildFromTemplate: items => items }, nativeImage: { createFromBitmap: bytes => bytes },
        dialog: { showErrorBox: (...args) => errors.push(args) }, shell: { openExternal: url => { urls.push(url); return Promise.resolve() } },
      }
      if (id === './tray-channel.cjs') return { TrayChannel: Channel }
      if (id === './tray-menu.cjs') return require(id)
      throw new Error(id)
    },
  })
  const host = exports.exports.startTray({ origin: 'http://127.0.0.1:8788', token: 'test' }, () => {})
  await tick()
  tray.emit('right-click')
  await tick()
  assert.ok(tray.menu.some(item => item.label === 'Working (0)'))
  const node = { graph_id: 'g', node_id: 'n', name: 'Agent', state: 'working', saved_at_ns: 123 }
  current = { recent: [node], working: [node] }
  tray.emit('right-click')
  await tick()
  assert.ok(tray.menu.some(item => item.label === 'Working (1)'))
  tray.menu.find(item => item.label?.startsWith('NewNode')).click()
  tray.menu.find(item => item.label?.startsWith('  Agent')).click()
  tray.menu.find(item => item.label === '退出 AgentPark').click()
  await tick()
  assert.equal(urls[0], 'http://127.0.0.1:8788/?desktop_action=new-node')
  assert.equal(requests.filter(item => item.action === 'snapshot').length, 3)
  const opened = requests.find(item => item.action === 'open-node').fields
  assert.equal(opened.graph_id, 'g')
  assert.equal(opened.node_id, 'n')
  assert.ok(requests.some(item => item.action === 'exit'))
  assert.equal(tray.destroyed, undefined) // Wait for backend shutdown, not just a menu click.
  host.dispose()
  assert.equal(tray.destroyed, true)
  assert.deepEqual(errors, [])
})
