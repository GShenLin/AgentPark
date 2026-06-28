import type { LinkEndpoint, LinkItem, LinkSession } from './context'
import { normalizePortIndex } from './boardModel'

export function createBoardLinkSession(options: {
  nodeId: string
  outputIndex: number
  pointerId: number
  position: { x: number; y: number }
}): LinkSession {
  return {
    from: { node: options.nodeId, index: normalizePortIndex(options.outputIndex, 0) },
    pointerId: options.pointerId,
    startX: options.position.x,
    startY: options.position.y,
    currentX: options.position.x,
    currentY: options.position.y,
  }
}

export function boardLinkExists(links: LinkItem[], from: LinkEndpoint, to: LinkEndpoint) {
  return links.some(
    (link) =>
      link.from.node === from.node &&
      link.from.index === from.index &&
      link.to.node === to.node &&
      link.to.index === to.index,
  )
}

export function createBoardLink(from: LinkEndpoint, to: LinkEndpoint): LinkItem {
  return {
    id: `link-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    from,
    to,
  }
}

export function createBoardLinkTarget(nodeId: string, inputIndex: number): LinkEndpoint {
  return { node: nodeId, index: normalizePortIndex(inputIndex, 0) }
}
