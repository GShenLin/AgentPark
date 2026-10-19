const { contextBridge, ipcRenderer } = require('electron')
contextBridge.exposeInMainWorld('annotations', {
  receive: callback => ipcRenderer.on('annotation:draw', (_event, value) => callback(value)),
  painted: (id, error) => ipcRenderer.send('annotation:painted', { id, error }),
})
