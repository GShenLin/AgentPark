const { contextBridge, ipcRenderer } = require('electron')
const target = ipcRenderer.sendSync('node-window:target')
contextBridge.exposeInMainWorld('agentParkNodeWindow', {
  target: Object.freeze(target),
  ready: () => ipcRenderer.send('node-window:ready'),
  fail: message => ipcRenderer.send('node-window:fail', String(message)),
  setMode: (mode, width, height, noteHeight) => ipcRenderer.invoke('node-window:mode', { mode, width, height, noteHeight }),
  retarget: nodeId => ipcRenderer.invoke('node-window:retarget', nodeId),
  beginDrag: () => ipcRenderer.send('node-window:drag-start'),
  moveDrag: () => ipcRenderer.send('node-window:drag-move'),
  endDrag: () => ipcRenderer.send('node-window:drag-end'),
  minimize: () => ipcRenderer.send('node-window:minimize'),
  openInBrowser: () => ipcRenderer.invoke('node-window:open-in-browser'),
  close: () => ipcRenderer.send('node-window:close'),
})
