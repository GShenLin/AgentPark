const path = require('node:path')
const ROOT = path.resolve(__dirname, '../..')

function parseLaunch(argv) {
  const read = key => argv.find(value => value.startsWith(`--${key}=`))?.slice(key.length + 3)
  const origin = new URL(read('origin'))
  if (origin.protocol !== 'http:' || origin.hostname !== '127.0.0.1' || !origin.port || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) {
    throw new Error('Node windows require a loopback AgentPark origin.')
  }
  const graphId = read('graph'), nodeId = read('node'), receipt = read('receipt')
  if (!graphId || !nodeId || !/^[a-f0-9]{32}$/.test(receipt || '')) throw new Error('Invalid node window target.')
  return { origin: origin.origin, graphId, nodeId, receipt }
}

function windowKey(target) { return JSON.stringify([target.origin, target.graphId, target.nodeId]) }
function receiptPath(id) {
  if (!/^[a-f0-9]{32}$/.test(id)) throw new Error('Invalid receipt ID.')
  return path.join(ROOT, '.runtime/node-windows', `${id}.json`)
}
module.exports = { ROOT, parseLaunch, windowKey, receiptPath }
