import type { NodeCard } from './context'
import { nodeCardHeight, nodeCardWidth } from './boardModel'

export type BoardSize = {
  width: number
  height: number
}

export const BOARD_CANVAS_PADDING_PX = 40
export const BOARD_PAN_EXPAND_MARGIN_PX = 120
export const BOARD_PAN_EXPAND_STEP_PX = 600

export type BoardPanCapacity = {
  canvasWidth: number
  canvasHeight: number
  canvasPaddingLeft: number
  canvasPaddingTop: number
  scrollLeft: number
  scrollTop: number
  expanded: boolean
}

export function computeBoardCanvasSize(options: {
  nodes: NodeCard[]
  cardWidth: number
  cardHeight: number
  padding: number
  emptyWidth: number
  emptyHeight: number
  minWidth: number
  minHeight: number
}): BoardSize {
  if (!options.nodes.length) {
    return { width: options.emptyWidth, height: options.emptyHeight }
  }
  const maxX = Math.max(...options.nodes.map((node) => node.ui.x + nodeCardWidth(node))) + options.padding * 2
  const maxY = Math.max(...options.nodes.map((node) => node.ui.y + nodeCardHeight(node))) + options.padding * 2
  return {
    width: Math.max(options.minWidth, Math.ceil(maxX)),
    height: Math.max(options.minHeight, Math.ceil(maxY)),
  }
}

export function assignMissingNodePositions(options: {
  nodes: NodeCard[]
  cardWidth: number
  cardHeight: number
  padding: number
  gap: number
}) {
  let idx = 0
  for (const node of options.nodes) {
    if (node.ui) continue
    const col = idx % 4
    const row = Math.floor(idx / 4)
    node.ui = {
      x: options.padding + col * (options.cardWidth + options.gap),
      y: options.padding + row * (options.cardHeight + options.gap),
    }
    idx += 1
  }
}

export function nodeCardStyle(options: {
  node: NodeCard | undefined
  dragging: boolean
}): Record<string, string | number> {
  const x = options.node?.ui?.x ?? 0
  const y = options.node?.ui?.y ?? 0
  return {
    left: `${x}px`,
    top: `${y}px`,
    width: `${nodeCardWidth(options.node)}px`,
    height: `${nodeCardHeight(options.node)}px`,
    zIndex: options.dragging ? 10 : 1,
  }
}

export function canvasPointFromClient(options: {
  canvas: HTMLElement | null
  clientX: number
  clientY: number
  scale: number
  contentOffsetLeft?: number
  contentOffsetTop?: number
}) {
  const canvas = options.canvas
  if (!canvas) return { x: 0, y: 0 }
  const rect = canvas.getBoundingClientRect()
  const style = window.getComputedStyle(canvas)
  const paddingLeft = options.contentOffsetLeft ?? (Number.parseFloat(style.paddingLeft || '0') || 0)
  const paddingTop = options.contentOffsetTop ?? (Number.parseFloat(style.paddingTop || '0') || 0)
  const scale = options.scale || 1
  return {
    x: (options.clientX - rect.left - paddingLeft) / scale,
    y: (options.clientY - rect.top - paddingTop) / scale,
  }
}

export function expandBoardPanCapacity(options: {
  startPointerX: number
  startPointerY: number
  startScrollLeft: number
  startScrollTop: number
  startCanvasPaddingLeft: number
  startCanvasPaddingTop: number
  clientX: number
  clientY: number
  clientWidth: number
  clientHeight: number
  canvasWidth: number
  canvasHeight: number
  canvasPaddingLeft: number
  canvasPaddingTop: number
  scale: number
  basePadding?: number
  edgeMargin?: number
  expandStep?: number
}): BoardPanCapacity {
  const scale = Math.max(options.scale || 1, 0.01)
  const basePadding = options.basePadding ?? BOARD_CANVAS_PADDING_PX
  const edgeMargin = options.edgeMargin ?? BOARD_PAN_EXPAND_MARGIN_PX
  const expandStep = options.expandStep ?? BOARD_PAN_EXPAND_STEP_PX
  const dx = options.clientX - options.startPointerX
  const dy = options.clientY - options.startPointerY
  const movingTowardLeft = dx > 0
  const movingTowardTop = dy > 0
  const movingTowardRight = dx < 0
  const movingTowardBottom = dy < 0
  let canvasWidth = options.canvasWidth
  let canvasHeight = options.canvasHeight
  let canvasPaddingLeft = options.canvasPaddingLeft
  let canvasPaddingTop = options.canvasPaddingTop
  let scrollLeft = options.startScrollLeft - dx + (canvasPaddingLeft - options.startCanvasPaddingLeft)
  let scrollTop = options.startScrollTop - dy + (canvasPaddingTop - options.startCanvasPaddingTop)
  let expanded = false

  if (movingTowardLeft && scrollLeft < edgeMargin) {
    const growBy = edgeMargin - scrollLeft + expandStep
    canvasPaddingLeft += growBy
    scrollLeft += growBy
    expanded = true
  }
  if (movingTowardTop && scrollTop < edgeMargin) {
    const growBy = edgeMargin - scrollTop + expandStep
    canvasPaddingTop += growBy
    scrollTop += growBy
    expanded = true
  }

  const scrollWidth = canvasWidth * scale + basePadding * 2 + canvasPaddingLeft
  const rightShortfall = scrollLeft + options.clientWidth - (scrollWidth - edgeMargin)
  if (movingTowardRight && rightShortfall > 0) {
    const growBy = rightShortfall + expandStep
    canvasWidth += Math.ceil(growBy / scale)
    expanded = true
  }

  const scrollHeight = canvasHeight * scale + basePadding * 2 + canvasPaddingTop
  const bottomShortfall = scrollTop + options.clientHeight - (scrollHeight - edgeMargin)
  if (movingTowardBottom && bottomShortfall > 0) {
    const growBy = bottomShortfall + expandStep
    canvasHeight += Math.ceil(growBy / scale)
    expanded = true
  }

  return {
    canvasWidth,
    canvasHeight,
    canvasPaddingLeft,
    canvasPaddingTop,
    scrollLeft,
    scrollTop,
    expanded,
  }
}
