import type { LinkItem, NodeCard } from './context'
import { clampX } from './boardModel'

export type BoardClipboardSnapshot = {
  nodes: NodeCard[]
  links: LinkItem[]
}

export type BoardPastePlan = {
  nodes: NodeCard[]
  links: LinkItem[]
  idMap: Map<string, string>
}

export function hasBoardClipboardSnapshot(value: BoardClipboardSnapshot | null) {
  return !!value && value.nodes.length > 0
}

export function makeBoardCopySnapshot(options: {
  nodes: NodeCard[]
  links: LinkItem[]
  selectedItemIds: string[]
}): BoardClipboardSnapshot | null {
  const selected = new Set<string>(options.selectedItemIds)
  if (!selected.size) return null
  const copiedNodes = options.nodes
    .filter((node) => selected.has(node.id))
    .map(copyNodeForClipboard)
  if (!copiedNodes.length) return null

  const copiedIds = new Set<string>(copiedNodes.map((node) => node.id))
  const copiedLinks = options.links
    .filter((link) => copiedIds.has(link.from.node) && copiedIds.has(link.to.node))
    .map((link) => ({
      id: link.id,
      from: { node: link.from.node, index: link.from.index },
      to: { node: link.to.node, index: link.to.index },
    }))
  return { nodes: copiedNodes, links: copiedLinks }
}

export function buildBoardPastePlan(options: {
  snapshot: BoardClipboardSnapshot
  offset: number
  makeUniqueId: (base: string) => string
  makeLinkId: () => string
}): BoardPastePlan {
  const idMap = new Map<string, string>()
  const newNodes = options.snapshot.nodes.map((node) => {
    const nodeId = options.makeUniqueId(`${String(node.name || node.id || 'node').trim() || 'node'}1`)
    idMap.set(node.id, nodeId)
    return createPastedNodeCard(node, nodeId, options.offset)
  })
  const newLinks: LinkItem[] = []
  for (const link of options.snapshot.links) {
    const fromId = idMap.get(link.from.node)
    const toId = idMap.get(link.to.node)
    if (!fromId || !toId) continue
    newLinks.push({
      id: options.makeLinkId(),
      from: { node: fromId, index: link.from.index },
      to: { node: toId, index: link.to.index },
    })
  }
  return { nodes: newNodes, links: newLinks, idMap }
}

function copyNodeForClipboard(node: NodeCard): NodeCard {
  return {
    id: node.id,
    typeId: node.typeId,
    name: node.name,
    inputNum: node.inputNum,
    outputNum: node.outputNum,
    ui: { x: node.ui.x, y: node.ui.y },
    last_message: node.last_message,
    lastRuntimeEvent: null,
    runtimeEvents: [],
    providerId: node.providerId,
    mode: node.mode,
    webSearch: node.webSearch,
    thinking: node.thinking,
    reasoningEffort: node.reasoningEffort,
    systemPrompt: node.systemPrompt,
    plugins: Array.isArray(node.plugins) ? node.plugins.map(String).filter(Boolean) : [],
    tools: Array.isArray(node.tools) ? node.tools.map(String).filter(Boolean) : [],
    mcpServers: Array.isArray(node.mcpServers) ? node.mcpServers.map(String).filter(Boolean) : [],
    workingPath: node.workingPath,
  }
}

function createPastedNodeCard(node: NodeCard, nodeId: string, offset: number): NodeCard {
  return {
    id: nodeId,
    typeId: node.typeId,
    name: node.name,
    inputNum: node.inputNum,
    outputNum: node.outputNum,
    ui: { x: clampX(node.ui.x + offset), y: Math.max(0, node.ui.y + offset) },
    last_message: null,
    lastRuntimeEvent: null,
    runtimeEvents: [],
    providerId: node.providerId,
    mode: node.mode,
    webSearch: node.webSearch,
    thinking: node.thinking,
    reasoningEffort: node.reasoningEffort,
    systemPrompt: node.systemPrompt,
    plugins: Array.isArray(node.plugins) ? node.plugins.map(String).filter(Boolean) : [],
    tools: Array.isArray(node.tools) ? node.tools.map(String).filter(Boolean) : [],
    mcpServers: Array.isArray(node.mcpServers) ? node.mcpServers.map(String).filter(Boolean) : [],
    workingPath: node.workingPath,
  }
}
