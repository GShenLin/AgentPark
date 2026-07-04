const { app, BrowserWindow, ipcMain, screen, shell } = require('electron')
const path = require('path')

const DEFAULT_BASE_URL = process.env.AGENTPARK_BASE_URL || 'http://127.0.0.1:8766'
const INITIAL_OWNER_PID = Number.parseInt(process.env.AGENTPARK_OWNER_PID || '', 10)
const COLLAPSED_WINDOW_BOUNDS = { width: 150, height: 150 }
const BUBBLE_WINDOW_WIDTH = 280
const BUBBLE_WINDOW_AVATAR_HEIGHT = 118
const BUBBLE_WINDOW_GAP = 8
const BUBBLE_WINDOW_PADDING_Y = 24
const EXPANDED_WINDOW_BOUNDS = { width: 380, height: 520 }
const MENU_WINDOW_BOUNDS = { width: 260, height: 430 }
const windowsByViewId = new Map()
const ownerPidByViewId = new Map()
const positionSaveTimers = new Map()
let ownerMonitorTimer = null
logPet('process-start', { argv: process.argv, baseUrl: DEFAULT_BASE_URL, initialOwnerPid: INITIAL_OWNER_PID })
let pendingLaunch = parseLaunchArgs(process.argv, 'initial')

const gotSingleInstanceLock = app.requestSingleInstanceLock()
if (!gotSingleInstanceLock) {
  app.quit()
}

app.on('second-instance', (_event, argv) => {
  logPet('second-instance', { argv })
  const request = parseLaunchArgs(argv, 'second-instance')
  if (request) {
    void summonNodeView(request).catch((error) => {
      logPetError('failed to open second pet window', error, { request })
    })
  }
})

app.whenReady().then(async () => {
  app.setAppUserModelId('AgentPark.DesktopPet')
  ipcMain.handle('agentpark-pet:set-window-position', (_event, payload) => setWindowPosition(payload))
  ipcMain.handle('agentpark-pet:move-window-by', (event, payload) => moveWindowBy(event, payload))
  ipcMain.handle('agentpark-pet:set-window-layout', (event, payload) => setWindowLayout(event, payload))
  ipcMain.handle('agentpark-pet:open-main-page', () => openMainPageInBrowser())
  ipcMain.handle('agentpark-pet:hide-window', async (event, payload) => {
    const win = BrowserWindow.fromWebContents(event.sender)
    const viewId = String((payload && payload.view_id) || '').trim()
    if (win && !win.isDestroyed()) {
      win.hide()
      if (viewId) {
        markNodeViewHidden(viewId).catch((error) => {
          console.error('[AgentParkPet] failed to mark view hidden:', error)
        })
      }
      win.close()
    }
    return { ok: true }
  })
  if (pendingLaunch) {
    await summonNodeView(pendingLaunch).catch((error) => {
      logPetError('failed to open initial pet window', error, { request: pendingLaunch })
    })
    pendingLaunch = null
  }
})

app.on('window-all-closed', () => {})

app.on('before-quit', () => {
  if (ownerMonitorTimer) {
    clearInterval(ownerMonitorTimer)
    ownerMonitorTimer = null
  }
})

function logPet(event, payload = {}) {
  console.log(`[AgentParkPet] ${event} ${JSON.stringify(payload)}`)
}

function logPetError(message, error, payload = {}) {
  console.error(`[AgentParkPet] ${message} ${JSON.stringify({
    ...payload,
    error: error && error.stack ? String(error.stack) : String(error || ''),
  })}`)
}

function parseLaunchArgs(argv, source) {
  const args = Array.isArray(argv) ? argv : []
  const packedRequest = parsePackedLaunchRequest(args)
  if (packedRequest) {
    logPet('parse-launch-args-packed', { source, request: packedRequest, argv: args })
    return packedRequest
  }
  logPet('parse-launch-args-missing-packed-request', { source, argv: args })
  return null
}

function parsePackedLaunchRequest(args) {
  const prefix = '--agentpark-request='
  const rawArg = args.find((item) => String(item || '').startsWith(prefix))
  if (!rawArg) return null
  const encoded = String(rawArg).slice(prefix.length).trim()
  if (!encoded) return null
  try {
    const padded = encoded + '='.repeat((4 - (encoded.length % 4)) % 4)
    const payload = JSON.parse(Buffer.from(padded, 'base64url').toString('utf8'))
    const graphId = String((payload && payload.graph_id) || '').trim()
    const nodeId = String((payload && payload.node_id) || '').trim()
    if (!graphId || !nodeId) return null
    return {
      graph_id: graphId,
      node_id: nodeId,
      view_id: String((payload && payload.view_id) || '').trim(),
      owner_pid: Number.parseInt(String((payload && payload.owner_pid) || ''), 10),
      working_path: String((payload && payload.working_path) || '').trim(),
      draft_prefix: String((payload && payload.draft_prefix) || ''),
      open_chat: !!(payload && payload.open_chat),
      visible: true,
      pinned: !!(payload && payload.pinned),
    }
  } catch (error) {
    logPetError('failed to parse packed launch request', error, { encoded })
    return null
  }
}

function startOwnerMonitor() {
  if (ownerMonitorTimer) return
  if (ownerPidByViewId.size === 0) return
  ownerMonitorTimer = setInterval(() => {
    closeWindowsForExitedOwners()
    if (ownerPidByViewId.size === 0 && windowsByViewId.size === 0) app.quit()
  }, 1500)
  if (ownerMonitorTimer && typeof ownerMonitorTimer.unref === 'function') ownerMonitorTimer.unref()
}

function isProcessAlive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    const code = error && typeof error === 'object' ? error.code : ''
    return code === 'EPERM'
  }
}

function closeWindowsForExitedOwners() {
  const deadViewIds = []
  for (const [viewId, ownerPid] of ownerPidByViewId.entries()) {
    if (!isProcessAlive(ownerPid)) deadViewIds.push(viewId)
  }
  for (const viewId of deadViewIds) {
    ownerPidByViewId.delete(viewId)
    const win = windowsByViewId.get(viewId)
    if (win && !win.isDestroyed()) win.close()
  }
}

async function summonNodeView(request) {
  const viewId = String(request.view_id || '').trim()
  logPet('open-node-view-start', { request, mode: viewId ? 'get-view' : 'summon' })
  const response = viewId
    ? await fetchJson(`/api/node-desktop-views/${encodeURIComponent(viewId)}`)
    : await fetchJson('/api/node-desktop-views/summon', {
      method: 'POST',
      body: JSON.stringify(request),
    })
  if (!response.view || !response.view.view_id) {
    throw new Error('node desktop view response is missing view.view_id')
  }
  logPet('open-node-view-response', {
    requestedViewId: viewId,
    responseViewId: String(response.view.view_id || ''),
    graphId: String(response.view.graph_id || ''),
    nodeId: String(response.view.node_id || ''),
  })
  showPetWindow(response.view, resolveRequestOwnerPid(request), request)
}

async function fetchJson(route, init = {}) {
  const response = await fetch(`${DEFAULT_BASE_URL}${route}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  })
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    logPet('fetch-json-failed', { route, status: response.status, body: text.trim() })
    throw new Error(text.trim() || `HTTP ${response.status}`)
  }
  return response.json()
}

function showPetWindow(view, ownerPid, request = {}) {
  const viewId = String(view.view_id || '').trim()
  if (!viewId) throw new Error('view_id is required')
  bindWindowOwner(viewId, ownerPid)
  let win = windowsByViewId.get(viewId)
  if (win && !win.isDestroyed()) {
    logPet('show-window-reuse', { viewId, ownerPid, windowCount: windowsByViewId.size })
    if (hasViewPosition(view)) applyViewPosition(win, view)
    enforcePetAlwaysOnTop(win)
    win.show()
    enforcePetAlwaysOnTop(win)
    win.focus()
    sendAskHereRequest(win, request)
    return
  }

  win = new BrowserWindow({
    width: COLLAPSED_WINDOW_BOUNDS.width,
    height: COLLAPSED_WINDOW_BOUNDS.height,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    hasShadow: false,
    webPreferences: {
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  })
  enforcePetAlwaysOnTop(win)
  windowsByViewId.set(viewId, win)
  logPet('show-window-created', { viewId, ownerPid, windowCount: windowsByViewId.size })
  win.on('closed', () => {
    windowsByViewId.delete(viewId)
    ownerPidByViewId.delete(viewId)
    if (windowsByViewId.size === 0) app.quit()
  })
  win.on('moved', () => schedulePositionSave(viewId))
  win.on('show', () => enforcePetAlwaysOnTop(win))
  win.on('blur', () => enforcePetAlwaysOnTop(win))
  applyViewPosition(win, view)
  const url = buildPetUrl(viewId, request)
  logPet('show-window-load-url', { viewId, url })
  win.loadURL(url)
}

function enforcePetAlwaysOnTop(win) {
  if (!win || win.isDestroyed()) return
  win.setAlwaysOnTop(true, 'screen-saver')
  if (typeof win.setVisibleOnAllWorkspaces === 'function') {
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  }
  if (typeof win.moveTop === 'function') win.moveTop()
}

function buildPetUrl(viewId, request = {}) {
  const params = new URLSearchParams({ pet: '1', view_id: viewId })
  if (request.open_chat) params.set('open_chat', '1')
  const draftPrefix = String(request.draft_prefix || '')
  if (draftPrefix) params.set('draft_prefix', draftPrefix)
  return `${DEFAULT_BASE_URL}/?${params.toString()}`
}

function sendAskHereRequest(win, request = {}) {
  if (!request.open_chat && !String(request.draft_prefix || '')) return
  win.webContents.send('agentpark-pet:ask-here', {
    open_chat: !!request.open_chat,
    draft_prefix: String(request.draft_prefix || ''),
    working_path: String(request.working_path || ''),
  })
}

function resolveRequestOwnerPid(request) {
  const requestOwnerPid = Number.parseInt(String((request && request.owner_pid) || ''), 10)
  if (Number.isInteger(requestOwnerPid) && requestOwnerPid > 0) return requestOwnerPid
  return INITIAL_OWNER_PID
}

function bindWindowOwner(viewId, ownerPid) {
  const pid = Number.parseInt(String(ownerPid || ''), 10)
  if (!viewId || !Number.isInteger(pid) || pid <= 0 || pid === process.pid) return
  ownerPidByViewId.set(viewId, pid)
  startOwnerMonitor()
}

function markNodeViewHidden(viewId) {
  return fetchJson(`/api/node-desktop-views/${encodeURIComponent(viewId)}`, {
    method: 'POST',
    body: JSON.stringify({ visible: false }),
  })
}

function schedulePositionSave(viewId) {
  const existing = positionSaveTimers.get(viewId)
  if (existing) clearTimeout(existing)
  const timer = setTimeout(() => {
    positionSaveTimers.delete(viewId)
    const win = windowsByViewId.get(viewId)
    if (!win || win.isDestroyed()) return
    const [x, y] = win.getPosition()
    fetchJson(`/api/node-desktop-views/${encodeURIComponent(viewId)}`, {
      method: 'POST',
      body: JSON.stringify({ position: { x, y } }),
    }).catch((error) => console.error('[AgentParkPet] failed to save position:', error))
  }, 250)
  positionSaveTimers.set(viewId, timer)
}

function hasViewPosition(view) {
  const position = view && typeof view.position === 'object' ? view.position : null
  return !!(position && Number.isFinite(Number(position.x)) && Number.isFinite(Number(position.y)))
}

function applyViewPosition(win, view) {
  const position = view && typeof view.position === 'object' ? view.position : null
  if (position && Number.isFinite(Number(position.x)) && Number.isFinite(Number(position.y))) {
    win.setPosition(Number(position.x), Number(position.y), false)
    return
  }
  const area = screen.getPrimaryDisplay().workArea
  const offset = Math.max(0, windowsByViewId.size - 1) * 32
  win.setPosition(
    area.x + area.width - COLLAPSED_WINDOW_BOUNDS.width - 24 - offset,
    area.y + area.height - COLLAPSED_WINDOW_BOUNDS.height - 24 - offset,
    false,
  )
}

async function setWindowPosition(payload) {
  if (!payload || typeof payload !== 'object') throw new Error('payload must be object')
  const viewId = String(payload.view_id || '').trim()
  if (!viewId) throw new Error('view_id is required')
  const win = windowsByViewId.get(viewId)
  if (!win || win.isDestroyed()) throw new Error(`window not found: ${viewId}`)
  const [x, y] = win.getPosition()
  await fetchJson(`/api/node-desktop-views/${encodeURIComponent(viewId)}`, {
    method: 'POST',
    body: JSON.stringify({ position: { x, y } }),
  })
  return { ok: true, x, y }
}

function moveWindowBy(event, payload) {
  const win = BrowserWindow.fromWebContents(event.sender)
  if (!win || win.isDestroyed()) throw new Error('window not found')
  const deltaX = Number((payload && payload.delta_x) || 0)
  const deltaY = Number((payload && payload.delta_y) || 0)
  if (!Number.isFinite(deltaX) || !Number.isFinite(deltaY)) throw new Error('delta_x and delta_y must be finite numbers')
  const [x, y] = win.getPosition()
  win.setPosition(Math.round(x + deltaX), Math.round(y + deltaY), false)
  return { ok: true }
}

async function openMainPageInBrowser() {
  const url = new URL('/', DEFAULT_BASE_URL)
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error(`unsupported main page URL protocol: ${url.protocol}`)
  await shell.openExternal(url.toString())
  return { ok: true, url: url.toString() }
}

function setWindowLayout(event, payload) {
  const win = BrowserWindow.fromWebContents(event.sender)
  if (!win || win.isDestroyed()) throw new Error('window not found')
  const target = resolveWindowLayoutBounds(payload)
  const bounds = win.getBounds()
  const nextBounds = clampWindowBounds(
    bounds.x + bounds.width / 2 - target.width / 2,
    bounds.y + bounds.height - target.height,
    target.width,
    target.height,
    { preserveBottom: true },
  )
  win.setBounds(nextBounds, false)
  enforcePetAlwaysOnTop(win)
  return { ok: true, bounds: nextBounds }
}

function resolveWindowLayoutBounds(payload) {
  if (payload && payload.expanded) return { ...EXPANDED_WINDOW_BOUNDS, layout: 'expanded' }
  if (payload && payload.menu) return { ...MENU_WINDOW_BOUNDS, layout: 'menu' }
  if (payload && payload.bubble) {
    const bubbleHeight = Number(payload.bubble_height || 0)
    if (!Number.isFinite(bubbleHeight) || bubbleHeight < 0) throw new Error('bubble_height must be a non-negative finite number')
    return {
      width: BUBBLE_WINDOW_WIDTH,
      height: Math.max(
        COLLAPSED_WINDOW_BOUNDS.height,
        Math.ceil(bubbleHeight) + BUBBLE_WINDOW_AVATAR_HEIGHT + BUBBLE_WINDOW_GAP + BUBBLE_WINDOW_PADDING_Y,
      ),
      layout: 'bubble',
    }
  }
  return { ...COLLAPSED_WINDOW_BOUNDS, layout: 'collapsed' }
}

function clampWindowBounds(x, y, width, height, options = {}) {
  const display = screen.getDisplayMatching({ x, y, width, height })
  const area = display.workArea
  const maxX = area.x + area.width - width
  const maxY = area.y + area.height - height
  const bottom = Math.max(area.y + COLLAPSED_WINDOW_BOUNDS.height, Math.min(Math.round(y + height), area.y + area.height))
  return {
    x: Math.max(area.x, Math.min(Math.round(x), maxX)),
    y: options.preserveBottom ? bottom - height : Math.max(area.y, Math.min(Math.round(y), maxY)),
    width,
    height,
  }
}
