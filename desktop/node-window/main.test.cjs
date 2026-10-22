const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

function fixture(trayLaunch = true) {
  const handlers = new Map(), hosts = [], windows = []
  let quits = 0
  const app = {
    requestSingleInstanceLock: () => true,
    on: (name, handler) => handlers.set(name, handler),
    whenReady: () => Promise.resolve(),
    quit: () => { quits++ },
  }
  const target = trayLaunch ? { mode: 'tray', origin: 'http://127.0.0.1:8788', token: 'one' } : { nodeId: 'n' }
  vm.runInNewContext(fs.readFileSync(require.resolve('./main.cjs'), 'utf8'), {
    process: { argv: [] },
    require: id => {
      if (id === 'electron') return { app }
      if (id === './contract.cjs') return { parseHostLaunch: () => target, forwardedLaunch: value => value }
      if (id === './window-host.cjs') return { openNodeWindow: value => windows.push(value) }
      if (id === './tray-host.cjs') return { startTray: (value, disconnect) => {
        const host = { token: value.token, disconnect, disposed: false, dispose() { this.disposed = true } }
        hosts.push(host)
        return host
      } }
      throw new Error(id)
    },
  })
  return { handlers, hosts, windows, target, quits: () => quits }
}

test('closing every node window keeps the tray alive; backend disconnect exits the host', async () => {
  const f = fixture()
  await Promise.resolve()
  f.handlers.get('window-all-closed')()
  assert.equal(f.quits(), 0)
  f.handlers.get('second-instance')(null, null, null, { nodeId: 'n' })
  await Promise.resolve()
  assert.equal(f.windows.length, 1)
  f.hosts[0].disconnect()
  assert.equal(f.quits(), 1)
  assert.equal(f.hosts[0].disposed, true)
})

test('duplicate tray launches reuse the host and a new server capability replaces it', async () => {
  const f = fixture()
  await Promise.resolve()
  f.handlers.get('second-instance')(null, null, null, f.target)
  await Promise.resolve()
  assert.equal(f.hosts.length, 1)
  f.handlers.get('second-instance')(null, null, null, { ...f.target, token: 'two' })
  await Promise.resolve()
  assert.equal(f.hosts.length, 2)
  assert.equal(f.hosts[0].disposed, true)
  f.hosts[0].disconnect()
  assert.equal(f.quits(), 0)
  f.handlers.get('before-quit')()
  assert.equal(f.hosts[1].disposed, true)
})

test('a standalone node host still quits when its last window is closed', async () => {
  const f = fixture(false)
  await Promise.resolve()
  assert.equal(f.windows.length, 1)
  f.handlers.get('window-all-closed')()
  assert.equal(f.quits(), 1)
})
