const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { EventEmitter } = require('node:events')

function fixture() {
  const handlers = new Map(), files = new Map(), created = [], externalUrls = []
  const cursor = { x: 1000, y: 700 }
  class FakeWindow extends EventEmitter {
    constructor(options) {
      super(); this.options = options; this.rect = { x: 900, y: 600, width: options.width, height: options.height }
      this.webContents = new EventEmitter()
      Object.assign(this.webContents, {
        id: created.length + 1, mainFrame: { url: 'http://127.0.0.1:8788/' },
        session: { setPermissionRequestHandler: fn => { this.permission = fn } },
        setWindowOpenHandler: fn => { this.popup = fn }, getURL: () => this.webContents.mainFrame.url,
      })
      this.shown = 0; this.destroyed = false; created.push(this)
    }
    getBounds() { return { ...this.rect } }
    setBounds(rect) { this.rect = rect }
    setPosition(x, y) { this.rect = { ...this.rect, x, y } }
    loadURL(url) { this.url = url; return Promise.resolve() }
    show() { this.shown++ }
    focus() { this.focused = true }
    isMinimized() { return !!this.minimized }
    minimize() { this.minimized = true }
    restore() { this.minimized = false }
    isDestroyed() { return this.destroyed }
    close() { this.destroyed = true; this.emit('closed') }
  }
  const electron = {
    app: { setPath() {}, setName() {} }, BrowserWindow: FakeWindow,
    ipcMain: { on: (name, fn) => handlers.set(name, fn), handle: (name, fn) => handlers.set(name, fn) },
    screen: { getCursorScreenPoint: () => ({ ...cursor }), getDisplayMatching: () => ({ workArea: { x: 0, y: 0, width: 1280, height: 800 } }) },
    shell: { async openExternal(url) { externalUrls.push(url) } },
  }
  const fakeFs = {
    mkdirSync() {}, writeFileSync: (key, value) => files.set(key, value),
    renameSync: (from, to) => { files.set(to, files.get(from)); files.delete(from) },
  }
  const mod = { exports: {} }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'window-host.cjs'), 'utf8'), {
    module: mod, __dirname, URL, console,
    require: id => id === 'electron' ? electron : id === 'node:fs' ? fakeFs : require(id),
  })
  const target = { origin: 'http://127.0.0.1:8788', graphId: 'g', nodeId: 'n', receipt: 'a'.repeat(32) }
  const context = mod.exports.openNodeWindow(target)
  const event = { sender: context.win.webContents, senderFrame: context.win.webContents.mainFrame }
  return { ...mod.exports, handlers, files, created, context, target, event, cursor, externalUrls, shell: electron.shell }
}

test('browser links use the owning window graph and current renamed node, with encoded IDs', async () => {
  const f = fixture(), open = f.handlers.get('node-window:open-in-browser')
  f.context.target.graphId = '画布 / A & B'
  f.handlers.get('node-window:retarget')(f.event, '节点 + #?中文')
  await open(f.event, 'https://untrusted.example/')
  const url = new URL(f.externalUrls[0])
  assert.equal(url.origin, f.target.origin)
  assert.equal(url.pathname, '/')
  assert.equal(url.searchParams.get('graph'), '画布 / A & B')
  assert.equal(url.searchParams.get('node'), '节点 + #?中文')
  assert.equal(f.context.win.isDestroyed(), false)
  await assert.rejects(open({ ...f.event, senderFrame: {} }), /Untrusted/)
  f.shell.openExternal = async () => { throw new Error('Browser unavailable') }
  await assert.rejects(open(f.event), /Browser unavailable/)
})

test('launch acknowledgements wait for renderer readiness and repeated opens reuse one window', () => {
  const f = fixture()
  assert.equal(f.files.size, 0)
  f.openNodeWindow({ ...f.target, receipt: 'b'.repeat(32) })
  assert.equal(f.created.length, 1)
  f.handlers.get('node-window:ready')(f.event)
  assert.equal(f.files.size, 2)
  assert.ok([...f.files.values()].every(value => JSON.parse(value).ok === true))
  assert.equal(f.context.win.options.alwaysOnTop, true)
  assert.equal(f.context.win.options.webPreferences.nodeIntegration, false)
  assert.equal(f.context.win.options.webPreferences.sandbox, true)
})

test('chat expansion fits the display and collapsing restores card bounds', () => {
  const f = fixture(), mode = f.handlers.get('node-window:mode')
  mode(f.event, { mode: 'card', width: 280, height: 300 })
  const compact = { ...f.context.win.rect }
  mode(f.event, { mode: 'conversation', width: 2400, height: 1200 })
  assert.equal(f.context.win.rect.width, 1280)
  assert.equal(f.context.win.rect.height, 800)
  assert.equal(f.context.win.rect.x, 0)
  mode(f.event, { mode: 'card', width: 500, height: 500 })
  assert.deepEqual({ ...f.context.win.rect }, compact)
  assert.throws(() => mode(f.event, { mode: 'invalid', width: 20, height: 20 }))
})

test('minimizing keeps the node alive and reopening restores the same window', () => {
  const f = fixture(), minimize = f.handlers.get('node-window:minimize')
  assert.throws(() => minimize({ ...f.event, senderFrame: {} }))
  const other = f.openNodeWindow({ ...f.target, nodeId: 'other' })
  f.context.drag = { cursor: f.cursor, bounds: f.context.win.getBounds() }
  minimize(f.event)
  assert.equal(f.context.win.isMinimized(), true)
  assert.equal(f.context.win.isDestroyed(), false)
  assert.equal(other.win.isMinimized(), false)
  assert.equal(f.context.drag, null)
  assert.equal(f.windows.size, 2)
  assert.equal(f.openNodeWindow(f.target), f.context)
  assert.equal(f.context.win.isMinimized(), false)
  assert.equal(f.context.win.focused, true)
  assert.equal(f.created.length, 2)
})

test('independent nodes and graphs coexist, only an identical target reuses its window', () => {
  const f = fixture()
  for (let i = 0; i < 20; i++) f.openNodeWindow({ ...f.target, nodeId: `node-${i}` })
  f.openNodeWindow({ ...f.target, graphId: 'another-graph' })
  assert.equal(f.windows.size, 22)
  f.openNodeWindow(f.target)
  assert.equal(f.windows.size, 22)
  assert.equal(f.context.win.focused, true)
})

test('note space grows separately from the card, survives chat mode, and shrinks when removed', () => {
  const f = fixture(), mode = options => f.handlers.get('node-window:mode')(f.event, options)
  mode({ mode: 'card', width: 280, height: 348, noteHeight: 48 })
  f.handlers.get('node-window:ready')(f.event)
  assert.equal(f.context.win.rect.height, 348)
  // A user's resize is retained when the note wraps to another line.
  f.context.win.setBounds({ x: 10, y: 10, width: 320, height: 398 })
  mode({ mode: 'card', width: 280, height: 368, noteHeight: 68 })
  assert.equal(f.context.win.rect.width, 320)
  assert.equal(f.context.win.rect.height, 418)
  mode({ mode: 'conversation', width: 700, height: 600 })
  mode({ mode: 'card', width: 280, height: 388, noteHeight: 88 })
  assert.equal(f.context.win.rect.height, 438)
  mode({ mode: 'card', width: 280, height: 300, noteHeight: 0 })
  assert.equal(f.context.win.rect.height, 350)
  mode({ mode: 'card', width: 280, height: 300, noteHeight: 0 })
  assert.equal(f.context.win.rect.height, 350)
  assert.throws(() => mode({ mode: 'card', width: 280, height: 300, noteHeight: NaN }))
})

test('card dragging follows native screen coordinates without compounding deltas and stops on release/blur', () => {
  const f = fixture(), call = name => f.handlers.get(`node-window:drag-${name}`)(f.event)
  call('start')
  f.cursor.x += 40; f.cursor.y -= 20; call('move')
  assert.equal(f.context.win.rect.x, 940)
  assert.equal(f.context.win.rect.y, 580)
  f.cursor.x += 15; call('move')
  assert.equal(f.context.win.rect.x, 955)
  call('end'); f.cursor.x += 100; call('move')
  assert.equal(f.context.win.rect.x, 955)
  call('start'); f.context.win.emit('blur'); f.cursor.x += 100; call('move')
  assert.equal(f.context.win.rect.x, 955)
})

test('rename updates duplicate detection and preload identity, without exposing IPC to subframes', () => {
  const f = fixture()
  f.handlers.get('node-window:retarget')(f.event, 'renamed')
  f.handlers.get('node-window:target')(f.event)
  assert.equal(f.event.returnValue.nodeId, 'renamed')
  f.openNodeWindow({ ...f.target, nodeId: 'renamed', receipt: 'c'.repeat(32) })
  assert.equal(f.created.length, 1)
  assert.throws(() => f.handlers.get('node-window:close')({ ...f.event, senderFrame: {} }))
  f.context.win.close()
  assert.equal(f.windows.size, 0)
})

test('external navigation and non-audio permissions cannot gain desktop access', () => {
  const f = fixture()
  let prevented = false
  f.context.win.webContents.emit('will-navigate', { preventDefault: () => { prevented = true } }, 'https://other.example')
  assert.equal(prevented, true)
  let allowed
  f.context.win.permission(f.context.win.webContents, 'media', value => { allowed = value }, { mediaTypes: ['video'] })
  assert.equal(allowed, false)
  f.context.win.permission(f.context.win.webContents, 'media', value => { allowed = value }, { mediaTypes: ['audio'] })
  assert.equal(allowed, true)
})

test('a previously ready window cannot acknowledge success after reload failure', () => {
  const f = fixture()
  f.handlers.get('node-window:ready')(f.event)
  f.context.win.webContents.emit('did-start-loading')
  f.openNodeWindow({ ...f.target, receipt: 'b'.repeat(32) })
  assert.equal(f.files.size, 1)
  f.handlers.get('node-window:fail')(f.event, 'Bootstrap unavailable')
  f.openNodeWindow({ ...f.target, receipt: 'c'.repeat(32) })
  const results = [...f.files.values()].map(value => JSON.parse(value))
  assert.equal(results.length, 3)
  assert.equal(results[1].ok, false)
  assert.equal(results[2].error, 'Bootstrap unavailable')
})
