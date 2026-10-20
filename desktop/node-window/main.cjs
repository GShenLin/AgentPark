const { app } = require('electron')
const { parseLaunch } = require('./contract.cjs')
const { openNodeWindow } = require('./window-host.cjs')

function start() {
  const target = parseLaunch(process.argv)
  if (!app.requestSingleInstanceLock(target)) { app.quit(); return }
  app.on('second-instance', (_event, _argv, _cwd, data) => {
    // Validate the same contract for forwarded requests.
    const launch = parseLaunch([`--origin=${data.origin}`, `--graph=${data.graphId}`, `--node=${data.nodeId}`, `--receipt=${data.receipt}`,
      ...(data.requestId ? [`--interaction=${data.requestId}`] : [])])
    void app.whenReady().then(() => openNodeWindow(launch))
  })
  void app.whenReady().then(() => openNodeWindow(target))
  app.on('window-all-closed', () => app.quit())
}
start()
