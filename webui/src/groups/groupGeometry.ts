import type { AgentGroup, GroupBounds } from './groupApi'
import type { NodeCard } from '../components/agent-board/context'
import { gridPositionToBoardPoint, type BoardGridSettings } from '../components/agent-board/boardGrid'
import { nodeCardHeight, nodeCardWidth } from '../components/agent-board/boardModel'

export function groupBounds(nodes: NodeCard[], grid: BoardGridSettings): GroupBounds {
  if (!nodes.length) throw new Error('请选择需要分组的 Agent。')
  const rects = nodes.map(node => ({ ...gridPositionToBoardPoint(node.ui, grid),
    width: Math.ceil(nodeCardWidth(node) / grid.cellWidth) * grid.cellWidth,
    height: Math.ceil(nodeCardHeight(node) / grid.cellHeight) * grid.cellHeight }))
  const x = Math.min(...rects.map(rect => rect.x))
  const y = Math.min(...rects.map(rect => rect.y))
  return { x, y, width: Math.max(...rects.map(rect => rect.x + rect.width)) - x,
    height: Math.max(...rects.map(rect => rect.y + rect.height)) - y }
}

export type ResizeEdge = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'
export function resizeGroupBounds(bounds: GroupBounds, edge: ResizeEdge, dx: number, dy: number, grid: BoardGridSettings): GroupBounds {
  const snapX = (x: number) => Math.max(0, Math.round(x / grid.cellWidth) * grid.cellWidth)
  const snapY = (y: number) => Math.max(0, Math.round(y / grid.cellHeight) * grid.cellHeight)
  let left = snapX(bounds.x), top = snapY(bounds.y)
  let right = Math.max(left + grid.cellWidth, snapX(bounds.x + bounds.width))
  let bottom = Math.max(top + grid.cellHeight, snapY(bounds.y + bounds.height))
  if (edge.includes('w')) left = Math.min(right - grid.cellWidth, snapX(bounds.x + dx))
  if (edge.includes('n')) top = Math.min(bottom - grid.cellHeight, snapY(bounds.y + dy))
  if (edge.includes('e')) right = Math.max(left + grid.cellWidth, snapX(bounds.x + bounds.width + dx))
  if (edge.includes('s')) bottom = Math.max(top + grid.cellHeight, snapY(bounds.y + bounds.height + dy))
  return { x: left, y: top, width: right - left, height: bottom - top }
}

export function containsPoint(bounds: GroupBounds, point: { x: number; y: number }) {
  return point.x >= bounds.x && point.y >= bounds.y && point.x < bounds.x + bounds.width && point.y < bounds.y + bounds.height
}

export function groupAtPoint(groups: AgentGroup[], point: { x: number; y: number }) {
  const matches = groups.filter(group => containsPoint(group.bounds, point))
  if (matches.length > 1) throw new Error('组边框重叠，无法确定目标组。请先调整组边框。')
  return matches[0] ?? null
}

export function nodeCenter(node: NodeCard, grid: BoardGridSettings) {
  const point = gridPositionToBoardPoint(node.ui, grid)
  return { x: point.x + nodeCardWidth(node) / 2, y: point.y + nodeCardHeight(node) / 2 }
}

export function boundsOverlap(a: GroupBounds, b: GroupBounds) {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y
}

export function selectionGroup(groups: AgentGroup[], ids: string[]) {
  return groups.find(group => group.members.length === ids.length && group.members.every(member => ids.includes(member.node_id))) ?? null
}
