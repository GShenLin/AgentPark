const { test } = require('node:test')
const assert = require('node:assert/strict')
const { parseLaunch, windowKey, receiptPath } = require('./contract.cjs')
const args = ['--origin=http://127.0.0.1:8788', '--graph=工作图', '--node=Agent A', `--receipt=${'a'.repeat(32)}`]
test('keeps Unicode and spaces without shell parsing', () => {
  assert.deepEqual(parseLaunch(args), { origin: 'http://127.0.0.1:8788', graphId: '工作图', nodeId: 'Agent A', receipt: 'a'.repeat(32) })
})
test('rejects remote origins, credentials, paths and receipt traversal', () => {
  for (const origin of ['https://example.com', 'http://127.0.0.1:8788/redirect', 'http://user@127.0.0.1:8788', 'file:///C:/file']) {
    assert.throws(() => parseLaunch([`--origin=${origin}`, ...args.slice(1)]))
  }
  assert.throws(() => receiptPath('../escape'))
})
test('deduplication distinguishes server and graph as well as node', () => {
  const target = parseLaunch(args)
  assert.notEqual(windowKey(target), windowKey({ ...target, graphId: 'another' }))
  assert.notEqual(windowKey(target), windowKey({ ...target, origin: 'http://127.0.0.1:9999' }))
  assert.equal(windowKey(target), windowKey({ ...target, receipt: 'b'.repeat(32) }))
})
