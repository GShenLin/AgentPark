const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

test('preload exposes an awaited text-copy bridge without exposing generic IPC', async () => {
  let bridge
  const calls = [], failure = new Error('Clipboard unavailable')
  let reject = false
  const electron = {
    contextBridge: { exposeInMainWorld(name, value) {
      assert.equal(name, 'agentParkNodeWindow')
      bridge = value
    } },
    ipcRenderer: {
      sendSync: () => ({ graphId: 'g', nodeId: 'n' }),
      invoke: async (...args) => { calls.push(args); if (reject) throw failure },
    },
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'preload.cjs'), 'utf8'), {
    require: id => { assert.equal(id, 'electron'); return electron },
  })
  await bridge.copyText('中文\ntext')
  assert.deepEqual(calls, [['node-window:copy-text', '中文\ntext']])
  assert.equal(bridge.invoke, undefined)
  reject = true
  await assert.rejects(bridge.copyText('failure'), error => error === failure)
})
