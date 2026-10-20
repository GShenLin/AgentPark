const { app, BrowserWindow, clipboard, ipcMain, screen, shell } = require('electron')
const fs = require('node:fs')
const path = require('node:path')
const { ROOT, windowKey, receiptPath } = require('./contract.cjs')

// Separate from the browser profile. Windows survive the page that launched them.
app.setPath('userData', path.join(ROOT, '.runtime/node-window-profile'))
app.setName('AgentPark Node')
const windows = new Map()
const contexts = new Map()

function acknowledge(context, result) {
  for (const id of context.receipts.splice(0)) {
    const dest = receiptPath(id)
    fs.mkdirSync(path.dirname(dest), { recursive: true })
    fs.writeFileSync(`${dest}.tmp`, JSON.stringify(result))
    fs.renameSync(`${dest}.tmp`, dest)
  }
}

function resize(context, { mode, width, height, noteHeight }) {
  if (!['card', 'conversation'].includes(mode) || !Number.isFinite(width) || !Number.isFinite(height)) throw new Error('Invalid window dimensions.')
  if (noteHeight !== undefined && (mode !== 'card' || !Number.isFinite(noteHeight) || noteHeight < 0 || noteHeight > 248)) throw new Error('Invalid note height.')
  const win = context.win
  const sameMode = context.mode === mode
  if (context.mode !== mode) {
    context.bounds[context.mode] = win.getBounds()
    context.mode = mode
  }
  let desired = context.bounds[mode]
  if (noteHeight !== undefined) {
    // Notes occupy their own space. Preserve manually resized card dimensions,
    // including when a note changed while the conversation was expanded.
    const delta = noteHeight - (context.noteHeight ?? 0)
    if (sameMode && context.ready) desired = win.getBounds()
    if (desired) desired = { ...desired, height: desired.height + delta }
    context.noteHeight = noteHeight
    if (context.bounds.card && desired) context.bounds.card = desired
  }
  const area = screen.getDisplayMatching(win.getBounds()).workArea
  const w = Math.min(area.width, Math.max(240, Math.round(desired?.width ?? width)))
  const h = Math.min(area.height, Math.max(180, Math.round(desired?.height ?? height)))
  const x = Math.max(area.x, Math.min(desired?.x ?? win.getBounds().x, area.x + area.width - w))
  const y = Math.max(area.y, Math.min(desired?.y ?? win.getBounds().y, area.y + area.height - h))
  win.setBounds({ x, y, width: w, height: h })
}

function openNodeWindow(target) {
  const key = windowKey(target)
  const existing = windows.get(key)
  if (existing && !existing.win.isDestroyed()) {
    existing.receipts.push(target.receipt)
    if (existing.failure) acknowledge(existing, { ok: false, error: existing.failure })
    else if (existing.ready) acknowledge(existing, { ok: true })
    if (existing.win.isMinimized()) existing.win.restore()
    existing.win.show(); existing.win.focus()
    return existing
  }
  const win = new BrowserWindow({
    width: target.requestId ? 500 : 360, height: target.requestId ? 650 : 340,
    minWidth: target.requestId ? 340 : 240, minHeight: target.requestId ? 280 : 180,
    title: 'AgentPark · 小 Agent', show: false, frame: false, transparent: true,
    alwaysOnTop: true, resizable: true, backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'), sandbox: true,
      contextIsolation: true, nodeIntegration: false, backgroundThrottling: false,
    },
  })
  const context = { win, target, mode: 'card', bounds: {}, receipts: [target.receipt], ready: false, failure: '' }
  win.on('blur', () => { context.drag = null })
  windows.set(key, context); contexts.set(win.webContents.id, context)
  const fail = error => { context.ready = false; context.failure = error; acknowledge(context, { ok: false, error }) }
  win.webContents.on('did-start-loading', () => { context.ready = false; context.failure = '' })
  const trusted = url => { try { return new URL(url).origin === target.origin } catch { return false } }
  win.webContents.on('will-navigate', (event, url) => { if (!trusted(url)) event.preventDefault() })
  win.webContents.on('will-attach-webview', event => event.preventDefault())
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) void shell.openExternal(url)
    return { action: 'deny' }
  })
  win.webContents.session.setPermissionRequestHandler((contents, permission, callback, details) => {
    const owner = contexts.get(contents?.id)
    callback(!!owner && new URL(contents.getURL()).origin === owner.target.origin && permission === 'media' && !!details.mediaTypes?.length && details.mediaTypes.every(type => type === 'audio'))
  })
  win.webContents.on('render-process-gone', (_event, detail) => {
    console.error('Node renderer exited', detail.reason)
    fail(`Node renderer exited: ${detail.reason}`)
  })
  win.on('closed', () => {
    acknowledge(context, { ok: false, error: 'Node window closed before readiness.' })
    windows.delete(windowKey(context.target))
    for (const [id, value] of contexts) if (value === context) contexts.delete(id)
  })
  win.loadURL(`${target.origin}/`).catch(error => {
    console.error(error)
    fail(error.message)
    win.show()
  })
  // Bootstrap failures remain visible and explainable rather than a hidden process.
  win.once('ready-to-show', () => win.show())
  return context
}

function senderContext(event) {
  const context = contexts.get(event.sender.id)
  if (!context || event.senderFrame !== event.sender.mainFrame || new URL(event.senderFrame.url).origin !== context.target.origin) throw new Error('Untrusted node window sender.')
  return context
}
ipcMain.on('node-window:ready', event => {
  const context = senderContext(event)
  context.ready = true; acknowledge(context, { ok: true }); context.win.show()
})
ipcMain.on('node-window:target', event => {
  const context = contexts.get(event.sender.id)
  if (!context || event.senderFrame !== event.sender.mainFrame) { event.returnValue = null; return }
  event.returnValue = { graphId: context.target.graphId, nodeId: context.target.nodeId,
    ...(context.target.requestId ? { requestId: context.target.requestId } : {}) }
})
ipcMain.handle('node-window:retarget', (event, nodeId) => {
  const context = senderContext(event)
  if (context.target.requestId) throw new Error('Interaction window identity cannot be changed.')
  if (typeof nodeId !== 'string' || !nodeId.trim()) throw new Error('Invalid node identity.')
  const next = { ...context.target, nodeId }
  const existing = windows.get(windowKey(next))
  if (existing && existing !== context) throw new Error('A window for this node already exists.')
  windows.delete(windowKey(context.target))
  context.target = next
  windows.set(windowKey(next), context)
})
ipcMain.on('node-window:fail', (event, error) => {
  const context = senderContext(event)
  context.ready = false; context.failure = String(error)
  acknowledge(context, { ok: false, error: context.failure })
})
ipcMain.handle('node-window:mode', (event, options) => resize(senderContext(event), options))
ipcMain.handle('node-window:copy-text', (event, text) => {
  senderContext(event)
  if (typeof text !== 'string') throw new TypeError('Clipboard text must be a string.')
  clipboard.writeText(text)
})
ipcMain.handle('node-window:open-in-browser', async event => {
  const { target } = senderContext(event)
  const url = new URL('/', target.origin)
  url.searchParams.set('graph', target.graphId)
  url.searchParams.set('node', target.nodeId)
  await shell.openExternal(url.href)
})
ipcMain.on('node-window:close', event => senderContext(event).win.close())
ipcMain.on('node-window:minimize', event => {
  const context = senderContext(event)
  context.drag = null
  context.win.minimize()
})
ipcMain.on('node-window:drag-start', event => {
  const context = senderContext(event)
  if (context.mode === 'card') context.drag = { cursor: screen.getCursorScreenPoint(), bounds: context.win.getBounds() }
})
ipcMain.on('node-window:drag-move', event => {
  const context = senderContext(event), drag = context.drag
  if (!drag) return
  const cursor = screen.getCursorScreenPoint()
  context.win.setPosition(drag.bounds.x + cursor.x - drag.cursor.x, drag.bounds.y + cursor.y - drag.cursor.y)
})
ipcMain.on('node-window:drag-end', event => { senderContext(event).drag = null })

module.exports = { openNodeWindow, windows }
