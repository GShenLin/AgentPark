import type { NodeCard } from './context'

export type BoardSelectionSession = {
  startX: number
  startY: number
  currentX: number
  currentY: number
  additive: boolean
}

export type BoardSelectionRect = {
  x: number
  y: number
  width: number
  height: number
}

export function selectionRectFromSession(session: BoardSelectionSession | null): BoardSelectionRect | null {
  if (!session) return null
  const x = Math.min(session.startX, session.currentX)
  const y = Math.min(session.startY, session.currentY)
  const width = Math.abs(session.currentX - session.startX)
  const height = Math.abs(session.currentY - session.startY)
  return { x, y, width, height }
}

export function selectionRectExceedsThreshold(rect: BoardSelectionRect, threshold = 3) {
  return rect.width > threshold || rect.height > threshold
}

export function computeNodeIdsInSelectionRect(options: {
  nodes: NodeCard[]
  rect: BoardSelectionRect
  cardWidth: number
  cardHeight: number
}) {
  const selected = new Set<string>()
  const minX = options.rect.x
  const minY = options.rect.y
  const maxX = options.rect.x + options.rect.width
  const maxY = options.rect.y + options.rect.height
  for (const node of options.nodes) {
    const left = node.ui.x
    const top = node.ui.y
    const right = node.ui.x + options.cardWidth
    const bottom = node.ui.y + options.cardHeight
    const overlap = !(right < minX || left > maxX || bottom < minY || top > maxY)
    if (overlap) selected.add(node.id)
  }
  return selected
}
