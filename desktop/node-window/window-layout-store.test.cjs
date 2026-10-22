const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { WindowLayoutStore } = require('./window-layout-store.cjs')

function fixture(t) {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'node-window-layout-'))
  const filename = path.join(folder, 'layouts.json')
  t.after(() => {
    for (const file of [filename, `${filename}.tmp`]) {
      if (fs.existsSync(file)) fs.unlinkSync(file)
    }
    fs.rmdirSync(folder)
  })
  return { filename, store: new WindowLayoutStore(filename) }
}
const layout = { bounds: { card: { x: 80, y: 60, width: 680, height: 520 } }, noteHeight: 48 }

test('layouts survive disk round trips, isolate reads, and migrate renamed identities', t => {
  const { filename, store } = fixture(t)
  store.save('graph/节点', layout)
  const reopened = new WindowLayoutStore(filename)
  assert.deepEqual(reopened.get('graph/节点'), layout)
  reopened.get('graph/节点').bounds.card.width = 1
  assert.equal(reopened.get('graph/节点').bounds.card.width, 680)
  reopened.save('graph/renamed', layout, 'graph/节点')
  const renamed = new WindowLayoutStore(filename)
  assert.equal(renamed.get('graph/节点'), undefined)
  assert.deepEqual(renamed.get('graph/renamed'), layout)
  assert.equal(fs.existsSync(`${filename}.tmp`), false)
})

test('invalid layouts and corrupt files fail explicitly without replacing saved geometry', t => {
  const { filename, store } = fixture(t)
  store.save('node', layout)
  assert.throws(() => store.save('node', { bounds: { card: { x: NaN } }, noteHeight: 0 }), /Invalid/)
  assert.deepEqual(new WindowLayoutStore(filename).get('node'), layout)
  fs.writeFileSync(filename, '{broken', 'utf8')
  assert.throws(() => new WindowLayoutStore(filename), SyntaxError)
  fs.writeFileSync(filename, JSON.stringify({ version: 2, layouts: {} }), 'utf8')
  assert.throws(() => new WindowLayoutStore(filename), /Invalid/)
})
