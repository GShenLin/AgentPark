const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { EventEmitter } = require('node:events')

function fixture(files = new Map()) {
  const handlers = new Map(), created = [], externalUrls = [], copiedTexts = []
  const cursor = { x: 1000, y: 700 }
  class FakeWindow extends EventEmitter {
    constructor(options) {
      super(); this.options = options; this.rect = { x: options.x ?? 900, y: options.y ?? 600, width: options.width, height: options.height }
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
    close() { this.emit('close'); this.destroyed = true; this.emit('closed') }
  }
  const electron = {
    app: { setPath() {}, setName() {} }, BrowserWindow: FakeWindow,
    clipboard: { writeText: text => copiedTexts.push(text) },
    ipcMain: { on: (name, fn) => handlers.set(name, fn), handle: (name, fn) => handlers.set(name, fn) },
    screen: { getCursorScreenPoint: () => ({ ...cursor }), getDisplayMatching: () => ({ workArea: { x: 0, y: 0, width: 1280, height: 800 } }) },
    shell: { async openExternal(url) { externalUrls.push(url) } },
  }
  const fakeFs = {
    readFileSync: key => {
      if (!files.has(key)) throw Object.assign(new Error('Missing file'), { code: 'ENOENT' })
      return files.get(key)
    },
    mkdirSync() {}, writeFileSync: (key, value) => files.set(key, value),
    renameSync: (from, to) => { files.set(to, files.get(from)); files.delete(from) },
  }
  function loadModule(name) {
    const mod = { exports: {} }
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, name), 'utf8'), {
      module: mod, __dirname, URL, console,
      require: id => id === 'electron' ? electron : id === 'node:fs' ? fakeFs
        : id === './window-layout-store.cjs' ? loadModule(id) : require(id),
    })
    return mod.exports
  }
  const host = loadModule('window-host.cjs')
  const target = { origin: 'http://127.0.0.1:8788', graphId: 'g', nodeId: 'n', receipt: 'a'.repeat(32) }
  const context = host.openNodeWindow(target)
  const event = { sender: context.win.webContents, senderFrame: context.win.webContents.mainFrame }
  return { ...host, handlers, files, created, context, target, event, cursor, externalUrls, copiedTexts, clipboard: electron.clipboard, shell: electron.shell }
}

test('closing and restarting the host preserves node geometry through renderer initialization', () => {
  const f = fixture(), rect = { x: 80, y: 60, width: 680, height: 520 }
  f.handlers.get('node-window:mode')(f.event, { mode: 'card', width: 444, height: 546, noteHeight: 48 })
  f.handlers.get('node-window:ready')(f.event)
  f.context.win.setBounds(rect)
  f.context.win.close()
  const restarted = fixture(f.files)
  assert.deepEqual({ ...restarted.context.win.getBounds() }, rect)
  restarted.handlers.get('node-window:mode')(restarted.event, { mode: 'card', width: 444, height: 546, noteHeight: 48 })
  assert.deepEqual({ ...restarted.context.win.getBounds() }, rect)
  const other = restarted.openNodeWindow({ ...restarted.target, nodeId: 'other' })
  assert.equal(other.win.getBounds().width, 360)
  const otherGraph = restarted.openNodeWindow({ ...restarted.target, graphId: 'other' })
  assert.equal(otherGraph.win.getBounds().width, 360)
})

test('restoration fits disconnected displays and accounts for changed note height only once', () => {
  const f = fixture()
  f.handlers.get('node-window:mode')(f.event, { mode: 'card', width: 444, height: 546, noteHeight: 48 })
  f.handlers.get('node-window:ready')(f.event)
  f.context.win.setBounds({ x: 3000, y: -1000, width: 600, height: 500 })
  f.context.win.close()
  const reopened = f.openNodeWindow(f.target)
  assert.deepEqual({ ...reopened.win.getBounds() }, { x: 680, y: 0, width: 600, height: 500 })
  const event = { sender: reopened.win.webContents, senderFrame: reopened.win.webContents.mainFrame }
  const mode = () => f.handlers.get('node-window:mode')(event, { mode: 'card', width: 444, height: 566, noteHeight: 68 })
  mode(); mode()
  assert.equal(reopened.win.getBounds().height, 520)
})

test('renaming moves the saved layout to the new node identity', () => {
  const f = fixture(), rect = { x: 100, y: 120, width: 600, height: 500 }
  f.handlers.get('node-window:ready')(f.event)
  f.context.win.setBounds(rect)
  f.handlers.get('node-window:retarget')(f.event, 'renamed')
  f.context.win.close()
  const restarted = fixture(f.files)
  assert.equal(restarted.context.win.getBounds().width, 360)
  const renamed = restarted.openNodeWindow({ ...restarted.target, nodeId: 'renamed' })
  assert.deepEqual({ ...renamed.win.getBounds() }, rect)
})

test('edge resize anchors opposite edges, uses screen deltas, and ends on release or blur', () => {
  const f = fixture(), call = (name, edge) => f.handlers.get(`node-window:resize-${name}`)(f.event, edge)
  f.context.win.setBounds({ x: 100, y: 100, width: 500, height: 400 })
  f.context.drag = {}
  call('start', 'nw')
  assert.equal(f.context.drag, null)
  f.cursor.x += 40; f.cursor.y += 20; call('move')
  assert.deepEqual({ ...f.context.win.getBounds() }, { x: 140, y: 120, width: 460, height: 380 })
  f.cursor.x += 400; f.cursor.y += 400; call('move')
  assert.deepEqual({ ...f.context.win.getBounds() }, { x: 360, y: 320, width: 240, height: 180 })
  call('end'); f.cursor.x -= 100; call('move')
  assert.equal(f.context.win.getBounds().width, 240)
  call('start', 'se'); f.context.win.emit('blur'); f.cursor.x += 80; call('move')
  assert.equal(f.context.win.getBounds().width, 240)
  assert.throws(() => call('start', 'invalid'), /Invalid/)
  assert.throws(() => f.handlers.get('node-window:resize-start')({ ...f.event, senderFrame: {} }, 'se'), /Untrusted/)
})

test('native clipboard accepts text only from the registered top-level origin', () => {
  const f = fixture(), copy = f.handlers.get('node-window:copy-text')
  copy(f.event, '中文\n```typescript\nconst value = 1\n```')
  assert.deepEqual(f.copiedTexts, ['中文\n```typescript\nconst value = 1\n```'])
  assert.throws(() => copy(f.event, { text: 'invalid' }), /must be a string/)
  assert.throws(() => copy({ ...f.event, senderFrame: {} }, 'subframe'), /Untrusted/)
  assert.throws(() => copy({ ...f.event, sender: { id: 999 } }, 'unknown'), /Untrusted/)
  f.event.senderFrame.url = 'https://other.example/'
  assert.throws(() => copy(f.event, 'external'), /Untrusted/)
  assert.equal(f.copiedTexts.length, 1)
  f.event.senderFrame.url = `${f.target.origin}/`
  f.clipboard.writeText = () => { throw new Error('Clipboard unavailable') }
  assert.throws(() => copy(f.event, 'failure'), /Clipboard unavailable/)
  f.context.win.close()
  assert.throws(() => copy(f.event, 'closed'), /Untrusted/)
})

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

test('interaction widgets coexist with their node window and other requests', () => {
  const f = fixture()
  const target = { ...f.target, requestId: 'c'.repeat(32) }
  const widget = f.openNodeWindow(target)
  f.openNodeWindow({ ...target, requestId: 'd'.repeat(32) })
  assert.equal(f.windows.size, 3)
  assert.equal(f.openNodeWindow(target), widget)
  const event = { sender: widget.win.webContents, senderFrame: widget.win.webContents.mainFrame }
  f.handlers.get('node-window:target')(event)
  assert.equal(event.returnValue.requestId, target.requestId)
  assert.throws(() => f.handlers.get('node-window:retarget')(event, 'other'), /cannot be changed/)
  widget.win.close()
  assert.equal(f.windows.size, 2)
  assert.equal(f.context.win.isDestroyed(), false)
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
