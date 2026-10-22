const { app } = require('electron')
const { parseHostLaunch, forwardedLaunch } = require('./contract.cjs')
const { openNodeWindow } = require('./window-host.cjs')
const { startTray } = require('./tray-host.cjs')
const trays = new Map()

function launch(target) {
  if (target.mode !== 'tray') { openNodeWindow(target); return }
  const previous = trays.get(target.origin)
  if (previous?.token === target.token) return
  previous?.dispose()
  const host = startTray(target, () => {
    if (trays.get(target.origin) !== host) return
    host.dispose()
    trays.delete(target.origin)
    if (!trays.size) app.quit()
  })
  trays.set(target.origin, host)
}

function start() {
  const target = parseHostLaunch(process.argv)
  if (!app.requestSingleInstanceLock(target)) { app.quit(); return }
  app.on('second-instance', (_event, _argv, _cwd, data) => {
    // Validate the same contract for forwarded requests.
    const target = forwardedLaunch(data)
    void app.whenReady().then(() => launch(target))
  })
  void app.whenReady().then(() => launch(target))
  app.on('window-all-closed', () => { if (!trays.size) app.quit() })
  app.on('before-quit', () => { for (const tray of trays.values()) tray.dispose(); trays.clear() })
}
start()
