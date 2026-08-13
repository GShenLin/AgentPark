export type BoardPosition = {
  grid_x: number
  grid_y: number
}

export function didBoardItemsChangeGridPosition(options: {
  itemIds: Iterable<string>
  startPositions: Readonly<Record<string, BoardPosition>>
  getPosition: (itemId: string) => BoardPosition | null
}) {
  for (const itemId of options.itemIds) {
    const start = options.startPositions[itemId]
    const current = options.getPosition(itemId)
    if (!start || !current) return true
    if (start.grid_x !== current.grid_x || start.grid_y !== current.grid_y) return true
  }
  return false
}

export function traceBoardDrag(event: string, payload: Record<string, unknown>) {
  if (typeof window === 'undefined') return
  const entry = {
    ts: new Date().toISOString(),
    event,
    ...payload,
  }
  const bag = window as unknown as { __agentBoardDragTrace?: unknown[] }
  const trace = Array.isArray(bag.__agentBoardDragTrace) ? bag.__agentBoardDragTrace : []
  trace.push(entry)
  if (trace.length > 300) trace.shift()
  bag.__agentBoardDragTrace = trace
  console.debug('[board-drag]', entry)
}

export function rememberPendingBoardPositions(options: {
  itemIds: Iterable<string>
  pending: Map<string, BoardPosition>
  reason: string
  getPosition: (itemId: string) => BoardPosition | null
}) {
  for (const itemId of options.itemIds) {
    const rawPosition = options.getPosition(itemId)
    if (!rawPosition) continue
    const pos = {
      grid_x: Math.max(0, Math.round(rawPosition.grid_x)),
      grid_y: Math.max(0, Math.round(rawPosition.grid_y)),
    }
    options.pending.set(itemId, pos)
    traceBoardDrag('ui_pending', { itemId, reason: options.reason, gridX: pos.grid_x, gridY: pos.grid_y })
  }
}

export function clearPendingBoardPosition(options: {
  itemId: string
  pending: Map<string, BoardPosition>
  reason: string
}) {
  if (!options.pending.has(options.itemId)) return
  options.pending.delete(options.itemId)
  traceBoardDrag('ui_pending_cleared', { itemId: options.itemId, reason: options.reason })
}
