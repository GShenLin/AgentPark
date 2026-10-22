const RESIZE_EDGES = new Set(['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'])

function fitBounds(bounds, area, minimum = { width: 240, height: 180 }) {
  const width = Math.min(area.width, Math.max(minimum.width, Math.round(bounds.width)))
  const height = Math.min(area.height, Math.max(minimum.height, Math.round(bounds.height)))
  return {
    x: Math.max(area.x, Math.min(Math.round(bounds.x), area.x + area.width - width)),
    y: Math.max(area.y, Math.min(Math.round(bounds.y), area.y + area.height - height)),
    width, height,
  }
}

// Use the initial native screen coordinates so moving the top/left edge cannot
// compound renderer-relative deltas. The opposite edge stays anchored at limits.
function resizeBounds(start, edge, delta, minimum) {
  if (!RESIZE_EDGES.has(edge)) throw new Error('Invalid window resize edge.')
  const width = Math.max(minimum.width, start.width + (edge.includes('e') ? delta.x : edge.includes('w') ? -delta.x : 0))
  const height = Math.max(minimum.height, start.height + (edge.includes('s') ? delta.y : edge.includes('n') ? -delta.y : 0))
  return {
    x: start.x + (edge.includes('w') ? start.width - width : 0),
    y: start.y + (edge.includes('n') ? start.height - height : 0),
    width, height,
  }
}

module.exports = { RESIZE_EDGES, fitBounds, resizeBounds }
