const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')

function renderer() {
  const makeNode = () => ({ attrs: {}, children: [],
    setAttribute(key, value) { this.attrs[key] = value },
    appendChild(child) { this.children.push(child) },
    replaceChildren() { this.children = [] }, getBBox() { return { width: 100 } } })
  const canvas = makeNode(), callbacks = [], painted = []
  let receive, now = 0
  const window = { innerWidth: 400, innerHeight: 300,
    annotations: { receive(fn) { receive = fn }, painted(...args) { painted.push(args) } } }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'renderer.js'), 'utf8'), {
    window, document: { getElementById: () => canvas, createElementNS: makeNode },
    requestAnimationFrame: callback => callbacks.push(callback), performance: { now: () => now },
  })
  return { window, canvas, painted, receive,
    async paint(elapsed = 16) {
      now += elapsed
      const current = callbacks.splice(0)
      current.forEach(callback => callback(now))
      await Promise.resolve(); await Promise.resolve()
    } }
}
const ellipse = { kind: 'ellipse', x: .25, y: .2, width: .5, height: .4, color: 'red' }
const draw = (shapes = [ellipse]) => ({ action: 'replace', duration_seconds: 10, shapes })

test('uses selected display geometry, not the stale 400x300 viewport; acknowledges only after resize', async () => {
  const h = renderer()
  const done = h.receive({ id: '1', viewport: { width: 1920, height: 1080 }, drawing: draw() })
  const attrs = h.canvas.children[0].attrs
  assert.equal(attrs.cx, '960'); assert.equal(attrs.cy, '432')
  assert.equal(attrs.rx, '480'); assert.equal(attrs.ry, '216')
  assert.equal(h.canvas.attrs.viewBox, '0 0 1920 1080')
  assert.equal(h.canvas.attrs.preserveAspectRatio, 'none')
  await h.paint(); await h.paint()
  assert.equal(h.painted.length, 0)
  h.window.innerWidth = 1920; h.window.innerHeight = 1080
  await h.paint(); assert.equal(h.painted.length, 0)
  await h.paint(); await done
  assert.deepEqual(h.painted, [['1']])
})

test('maps downsampled normalized coordinates to DIP exactly once at mixed DPI', async () => {
  const h = renderer()
  // 3840x2160 physical monitor at 200%, sampled to 800x450. Its global
  // origin (including negative multi-monitor positions) is not added here.
  h.window.innerWidth = 1920; h.window.innerHeight = 1080
  const done = h.receive({ id: '2', viewport: { width: 1920, height: 1080 }, drawing: draw([
    { kind: 'arrow', x: 200 / 800, y: 90 / 450, to_x: 600 / 800, to_y: 360 / 450, color: 'cyan' },
    { kind: 'text', x: .25, y: .99, text: 'bottom', color: 'white' },
  ]) })
  assert.match(h.canvas.children[0].attrs.d, /^M 480 216 L 1440 864 /)
  assert.equal(h.canvas.children[1].attrs.y, '1069.2') // No silent upward repositioning.
  await h.paint(); await h.paint(); await done
  assert.deepEqual(h.painted, [['2']])
})

test('rejects a viewport that never synchronizes instead of reporting misplaced marks as painted', async () => {
  const h = renderer()
  const done = h.receive({ id: '3', viewport: { width: 2560, height: 1440 }, drawing: draw() })
  await h.paint(2100); await done
  assert.match(h.painted[0][1], /尺寸/)
  assert.equal(h.canvas.children.length, 0)
})

test('switching to a portrait monitor replaces the previous coordinate system', async () => {
  const h = renderer()
  for (const [width, height] of [[1920, 1080], [1080, 1920]]) {
    const done = h.receive({ id: `${width}`, viewport: { width, height }, drawing: draw() })
    h.window.innerWidth = width; h.window.innerHeight = height
    await h.paint(); await h.paint(); await done
    assert.equal(h.canvas.children.length, 1)
    assert.equal(h.canvas.children[0].attrs.cx, String(width / 2))
    assert.equal(h.canvas.children[0].attrs.cy, String(height * .4))
  }
})
