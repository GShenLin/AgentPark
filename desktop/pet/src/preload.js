const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('agentParkPet', {
  saveWindowPosition(viewId) {
    return ipcRenderer.invoke('agentpark-pet:set-window-position', { view_id: viewId })
  },
  hideWindow(viewId) {
    return ipcRenderer.invoke('agentpark-pet:hide-window', { view_id: viewId })
  },
  moveWindowBy(deltaX, deltaY) {
    return ipcRenderer.invoke('agentpark-pet:move-window-by', { delta_x: deltaX, delta_y: deltaY })
  },
  setWindowLayout(viewId, payload) {
    return ipcRenderer.invoke('agentpark-pet:set-window-layout', {
      view_id: viewId,
      expanded: !!(payload && payload.expanded),
      menu: !!(payload && payload.menu),
      bubble: !!(payload && payload.bubble),
      bubble_height: Number((payload && payload.bubbleHeight) || 0),
      panel_width: Number((payload && payload.panelSize && payload.panelSize.width) || 0),
      panel_height: Number((payload && payload.panelSize && payload.panelSize.height) || 0),
      resize_anchor: String((payload && payload.resizeAnchor) || ''),
    })
  },
  log(event, payload) {
    return ipcRenderer.invoke('agentpark-pet:log', {
      event: String(event || ''),
      payload: payload || {},
    })
  },
  openMainPage() {
    return ipcRenderer.invoke('agentpark-pet:open-main-page')
  },
  onAskHere(callback) {
    if (typeof callback !== 'function') return () => {}
    const listener = (_event, payload) => callback(payload || {})
    ipcRenderer.on('agentpark-pet:ask-here', listener)
    return () => ipcRenderer.removeListener('agentpark-pet:ask-here', listener)
  },
})
