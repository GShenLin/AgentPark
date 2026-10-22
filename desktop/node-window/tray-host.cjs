const { Tray, Menu, nativeImage, dialog, shell } = require('electron')
const { TrayChannel } = require('./tray-channel.cjs')
const { trayMenu, validateSnapshot } = require('./tray-menu.cjs')

function trayIcon() {
  // A crisp opaque blue tile with a white A; no downloaded icon dependency.
  const size = 32, pixels = Buffer.alloc(size * size * 4)
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const i = (y * size + x) * 4
    const inset = Math.abs(x - 15.5)
    const white = y >= 6 && y <= 25 && ((inset >= (y - 6) * 0.36 && inset <= (y - 6) * 0.36 + 3)
      || (y >= 18 && y <= 21 && inset <= 7))
    pixels[i] = white ? 255 : 216
    pixels[i + 1] = white ? 255 : 105
    pixels[i + 2] = white ? 255 : 40
    pixels[i + 3] = 255
  }
  return nativeImage.createFromBitmap(pixels, { width: size, height: size })
}

function startTray(target, onDisconnect) {
  const tray = new Tray(trayIcon())
  tray.setToolTip('AgentPark · 正在连接')
  let disposed = false, opening = false
  const channel = new TrayChannel(target, () => { if (!disposed) onDisconnect() })
  const report = error => {
    console.error('Desktop tray:', error)
    if (!disposed) dialog.showErrorBox('AgentPark', error.message)
  }
  const run = operation => { Promise.resolve().then(operation).catch(report) }
  const command = action => () => run(() => channel.request(action))
  const actions = {
    openApp: () => run(() => shell.openExternal(`${target.origin}/`)),
    newNode: () => run(() => shell.openExternal(`${target.origin}/?desktop_action=new-node`)),
    openNode: node => run(() => channel.request('open-node', { graph_id: node.graph_id, node_id: node.node_id })),
    console: command('console'), restart: command('restart'), exit: command('exit'),
  }
  async function snapshot() {
    const state = validateSnapshot(await channel.request('snapshot'))
    if (!disposed) tray.setToolTip(`AgentPark · 运行中 · Working ${state.working.length}`)
    return state
  }
  channel.ready.then(snapshot).catch(report)
  tray.on('double-click', actions.openApp)
  tray.on('right-click', () => {
    if (opening) return
    opening = true
    snapshot().then(state => {
      if (!disposed) tray.popUpContextMenu(Menu.buildFromTemplate(trayMenu(state, actions)))
    }).catch(error => {
      console.error('Desktop tray snapshot:', error)
      if (!disposed) tray.popUpContextMenu(Menu.buildFromTemplate([
        { label: `菜单加载失败：${error.message}`, enabled: false },
        { label: '打开 AgentPark', click: actions.openApp },
        { label: '退出 AgentPark', click: actions.exit },
      ]))
    }).finally(() => { opening = false })
  })
  return { token: target.token, dispose() { disposed = true; channel.dispose(); tray.destroy() } }
}

module.exports = { startTray }
