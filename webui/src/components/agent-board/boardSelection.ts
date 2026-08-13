import type { NodeCard } from './context'
import { nodeCardHeight, nodeCardWidth } from './boardModel'
import { gridPositionToBoardPoint, type BoardGridSettings } from './boardGrid'

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

export function resolveNodeMoveIds(selectedIds: readonly string[], pressedId: string) {
  return selectedIds.includes(pressedId) ? [...selectedIds] : [pressedId]
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
  grid: BoardGridSettings
}) {
  const selected = new Set<string>()
  const minX = options.rect.x
  const minY = options.rect.y
  const maxX = options.rect.x + options.rect.width
  const maxY = options.rect.y + options.rect.height
  for (const node of options.nodes) {
    const point = gridPositionToBoardPoint(node.ui, options.grid)
    const left = point.x
    const top = point.y
    const right = point.x + nodeCardWidth(node)
    const bottom = point.y + nodeCardHeight(node)
    const overlap = !(right < minX || left > maxX || bottom < minY || top > maxY)
    if (overlap) selected.add(node.id)
  }
  return selected
}
