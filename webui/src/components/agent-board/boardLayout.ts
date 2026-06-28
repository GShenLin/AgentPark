import type { NodeCard } from './context'

export type BoardSize = {
  width: number
  height: number
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
  const points = options.nodes.map((node) => ({ x: node.ui.x, y: node.ui.y }))
  if (!points.length) {
    return { width: options.emptyWidth, height: options.emptyHeight }
  }
  const maxX = Math.max(...points.map((point) => point.x)) + options.cardWidth + options.padding * 2
  const maxY = Math.max(...points.map((point) => point.y)) + options.cardHeight + options.padding * 2
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
    zIndex: options.dragging ? 10 : 1,
  }
}

export function canvasPointFromClient(options: {
  canvas: HTMLElement | null
  clientX: number
  clientY: number
  scale: number
}) {
  const canvas = options.canvas
  if (!canvas) return { x: 0, y: 0 }
  const rect = canvas.getBoundingClientRect()
  const style = window.getComputedStyle(canvas)
  const paddingLeft = Number.parseFloat(style.paddingLeft || '0') || 0
  const paddingTop = Number.parseFloat(style.paddingTop || '0') || 0
  const scale = options.scale || 1
  return {
    x: (options.clientX - rect.left - paddingLeft) / scale,
    y: (options.clientY - rect.top - paddingTop) / scale,
  }
}
