import { clampX } from './boardModel'

export type BoardPosition = {
  x: number
  y: number
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

export function clampBoardPosition(pos: BoardPosition): BoardPosition {
  return {
    x: clampX(pos.x),
    y: Math.max(0, pos.y),
  }
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
    const pos = clampBoardPosition(rawPosition)
    options.pending.set(itemId, pos)
    traceBoardDrag('ui_pending', { itemId, reason: options.reason, x: pos.x, y: pos.y })
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
