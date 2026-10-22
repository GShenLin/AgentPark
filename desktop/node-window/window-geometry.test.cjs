const { test } = require('node:test')
const assert = require('node:assert/strict')
const { fitBounds, resizeBounds } = require('./window-geometry.cjs')

test('all eight resize directions track the cursor while keeping opposite edges fixed', () => {
  const start = { x: 100, y: 200, width: 500, height: 400 }, minimum = { width: 240, height: 180 }
  const expected = {
    n: [100, 230, 500, 370], s: [100, 200, 500, 430],
    e: [100, 200, 520, 400], w: [120, 200, 480, 400],
    ne: [100, 230, 520, 370], nw: [120, 230, 480, 370],
    se: [100, 200, 520, 430], sw: [120, 200, 480, 430],
  }
  for (const [edge, values] of Object.entries(expected)) {
    assert.deepEqual(Object.values(resizeBounds(start, edge, { x: 20, y: 30 }, minimum)), values, edge)
  }
})

test('fitting respects negative monitor coordinates and an oversized saved window', () => {
  assert.deepEqual(fitBounds({ x: -2000, y: -50, width: 2000, height: 1000 },
    { x: -1280, y: 0, width: 1280, height: 720 }), { x: -1280, y: 0, width: 1280, height: 720 })
})
