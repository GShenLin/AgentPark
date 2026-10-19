const { app, BrowserWindow, ipcMain, screen } = require('electron')
const path = require('node:path')
const fs = require('node:fs')

const identity = process.argv.find(value => value.startsWith('--annotation-id='))?.split('=')[1]
if (!/^[a-f0-9]{32}$/.test(identity || '')) throw new Error('Invalid annotation mailbox identity.')
const ownerPid = Number(process.argv.find(value => value.startsWith('--owner-pid='))?.split('=')[1])
if (!Number.isSafeInteger(ownerPid) || ownerPid <= 0) throw new Error('Missing annotation owner process.')
const mailbox = path.resolve(__dirname, '../../.runtime/annotations', identity)

app.setPath('userData', path.resolve(__dirname, '../../.runtime/annotation-profile'))
app.setName('AgentPark Screen Annotations')
let win, expiry, drawingDisplay
const pending = new Map()
const reply = value => {
  fs.writeFileSync(path.join(mailbox, 'response.tmp'), JSON.stringify(value), 'utf8')
  fs.renameSync(path.join(mailbox, 'response.tmp'), path.join(mailbox, 'response.json'))
}
function clear() { clearTimeout(expiry); if (win && !win.isDestroyed()) win.hide(); drawingDisplay = null }
function quit() { clear(); app.quit() }

async function render(id, drawing, viewport) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('Desktop renderer did not acknowledge drawing.')) }, 3000)
    pending.set(id, { resolve: () => { clearTimeout(timer); resolve() },
      reject: error => { clearTimeout(timer); reject(error) } })
    win.webContents.send('annotation:draw', { id, drawing, viewport })
  })
}

async function command(input) {
  if (!input || typeof input.id !== 'string') throw new Error('Invalid annotation command identity.')
  if (!['ping', 'clear', 'draw'].includes(input.action)) throw new Error('Unknown annotation command.')
  if (input.action === 'clear') clear()
  if (input.action === 'draw') {
    const display = screen.getAllDisplays().find(item => String(item.id) === input.display_id)
    if (!display) throw new Error('Selected display is no longer connected.')
    const drawing = input.drawing
    if (!drawing || !Array.isArray(drawing.shapes) || drawing.shapes.length > 12
        || !Number.isInteger(drawing.duration_seconds) || drawing.duration_seconds < 1 || drawing.duration_seconds > 60) throw new Error('Invalid drawing.')
    clear()
    if (drawing.action === 'replace') {
      win.setBounds(display.bounds)
      const actual = win.getContentBounds()
      if (['x', 'y', 'width', 'height'].some(key => actual[key] !== display.bounds[key])) {
        throw new Error('标注窗口未覆盖所选完整显示器，请重新选择显示器。')
      }
      // Normalized image coordinates map to this exact display's DIP bounds;
      // Chromium handles its physical pixel scale, including mixed-DPI layouts.
      await render(input.id, drawing, { width: display.bounds.width, height: display.bounds.height })
      drawingDisplay = String(display.id)
      win.showInactive()
      expiry = setTimeout(clear, drawing.duration_seconds * 1000)
    } else if (drawing.action !== 'clear') throw new Error('Invalid drawing action.')
  }
  reply({ id: input.id, ok: true, visible: win.isVisible(), display_id: drawingDisplay })
}

app.whenReady().then(async () => {
  win = new BrowserWindow({
    width: 400, height: 300, show: false, frame: false, transparent: true,
    backgroundColor: '#00000000', focusable: false, skipTaskbar: true, resizable: false,
    hasShadow: false, alwaysOnTop: true, title: 'AgentPark · AI 桌面标注',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), sandbox: true,
      contextIsolation: true, nodeIntegration: false, backgroundThrottling: false },
  })
  win.setIgnoreMouseEvents(true)
  win.setAlwaysOnTop(true, 'screen-saver')
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  win.webContents.on('will-navigate', event => event.preventDefault())
  win.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
  win.webContents.on('render-process-gone', () => { reply({ id: 'fatal', ok: false, error: 'Desktop renderer exited.' }); quit() })
  ipcMain.on('annotation:painted', (event, message) => {
    if (event.sender !== win.webContents || event.senderFrame !== win.webContents.mainFrame) return
    const waiting = pending.get(message.id)
    if (waiting) {
      pending.delete(message.id)
      if (message.error) waiting.reject(new Error(message.error)); else waiting.resolve()
    }
  })
  await win.loadFile(path.join(__dirname, 'overlay.html'))
  win.webContents.setZoomFactor(1)
  // A geometry change invalidates the user's explicit screen binding.
  for (const event of ['display-added', 'display-removed', 'display-metrics-changed']) screen.on(event, () => {
    reply({ id: 'fatal', ok: false, error: '显示器布局发生变化，请重新选择标注显示器。' }); quit()
  })
  const displays = screen.getAllDisplays().map((display, index) => ({
    id: String(display.id), label: display.label || `显示器 ${index + 1}`,
    width: Math.round(display.bounds.width * display.scaleFactor), height: Math.round(display.bounds.height * display.scaleFactor),
    x: display.bounds.x, y: display.bounds.y,
    physical_bounds: screen.dipToScreenRect(null, display.bounds),
  }))
  reply({ id: 'ready', ok: true, displays })
  let busy = false, lastId = ''
  setInterval(async () => {
    if (busy) return
    const file = path.join(mailbox, 'command.json')
    if (!fs.existsSync(file)) return
    busy = true
    let input
    try {
      const line = fs.readFileSync(file, 'utf8')
      if (line.length > 20000) throw new Error('Annotation command is too large.')
      input = JSON.parse(line)
      if (input.id !== lastId) { lastId = input.id; await command(input) }
    } catch (error) { clear(); reply({ id: input?.id || 'fatal', ok: false, error: error.message }) }
    finally { busy = false }
  }, 50)
  // The executing Python process owns this host, not a mobile timer. Signal 0
  // only checks process existence; it sends no signal and changes no process.
  setInterval(() => {
    try { process.kill(ownerPid, 0) }
    catch (error) {
      if (error.code !== 'ESRCH') console.error('Annotation owner check failed:', error.message)
      quit()
    }
  }, 1000)
}).catch(error => { reply({ id: 'fatal', ok: false, error: error.message }); quit() })
app.on('window-all-closed', () => app.quit())
