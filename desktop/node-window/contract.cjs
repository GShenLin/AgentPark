const path = require('node:path')
const ROOT = path.resolve(__dirname, '../..')

function parseOrigin(argv) {
  const read = key => argv.find(value => value.startsWith(`--${key}=`))?.slice(key.length + 3)
  const origin = new URL(read('origin'))
  if (origin.protocol !== 'http:' || origin.hostname !== '127.0.0.1' || !origin.port || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) {
    throw new Error('Node windows require a loopback AgentPark origin.')
  }
  return origin.origin
}

function parseLaunch(argv) {
  const read = key => argv.find(value => value.startsWith(`--${key}=`))?.slice(key.length + 3)
  const origin = parseOrigin(argv)
  const graphId = read('graph'), nodeId = read('node'), receipt = read('receipt')
  const requestId = read('interaction')
  if (!graphId || (!nodeId && !requestId) || !/^[a-f0-9]{32}$/.test(receipt || '')) throw new Error('Invalid node window target.')
  if (requestId !== undefined && !/^[a-f0-9]{32}$/.test(requestId)) throw new Error('Invalid interaction window target.')
  return { origin, graphId, nodeId, receipt, ...(requestId ? { requestId } : {}) }
}

function parseHostLaunch(argv) {
  if (!argv.includes('--tray')) return parseLaunch(argv)
  const token = argv.find(value => value.startsWith('--token='))?.slice(8)
  if (!/^[a-f0-9]{64}$/.test(token || '')) throw new Error('Invalid tray capability.')
  return { mode: 'tray', origin: parseOrigin(argv), token }
}

function forwardedLaunch(data) {
  return parseHostLaunch(data.mode === 'tray'
    ? ['--tray', `--origin=${data.origin}`, `--token=${data.token}`]
    : [`--origin=${data.origin}`, `--graph=${data.graphId}`, `--node=${data.nodeId}`, `--receipt=${data.receipt}`,
      ...(data.requestId ? [`--interaction=${data.requestId}`] : [])])
}

function windowKey(target) {
  return target.requestId
    ? JSON.stringify([target.origin, 'interaction', target.requestId])
    : JSON.stringify([target.origin, 'node', target.graphId, target.nodeId])
}
function receiptPath(id) {
  if (!/^[a-f0-9]{32}$/.test(id)) throw new Error('Invalid receipt ID.')
  return path.join(ROOT, '.runtime/node-windows', `${id}.json`)
}
module.exports = { ROOT, parseLaunch, parseHostLaunch, forwardedLaunch, windowKey, receiptPath }
