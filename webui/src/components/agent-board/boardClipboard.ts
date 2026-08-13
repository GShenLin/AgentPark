import type { LinkItem, NodeCard } from './context'
import { findAvailableGridGroup, sanitizeNodeGridUi, type BoardGridSettings, type NodeGridPosition, type NodeGridUi } from './boardGrid'
import { normalizeNodeNotes, type NodeNotes } from '../../nodeNotes'

export type BoardClipboardSnapshot = {
  graphId: string
  nodes: NodeCard[]
  links: LinkItem[]
  nodeNotes: NodeNotes
}

export type BoardPastePlan = {
  nodes: NodeCard[]
  links: LinkItem[]
  idMap: Map<string, string>
  nodeNotes: NodeNotes
}

export function makeBoardCopySnapshot(options: {
  graphId: string
  nodes: NodeCard[]
  links: LinkItem[]
  nodeNotes: NodeNotes
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
  const copiedNotes = Object.fromEntries(
    copiedNodes
      .map((node) => [node.id, options.nodeNotes[node.id]] as const)
      .filter((entry): entry is readonly [string, string] => !!entry[1]),
  )
  return { graphId: options.graphId, nodes: copiedNodes, links: copiedLinks, nodeNotes: copiedNotes }
}

export function buildBoardPastePlan(options: {
  snapshot: BoardClipboardSnapshot
  offset: number
  anchor?: NodeGridPosition
  occupied: Set<string>
  grid: BoardGridSettings
  makeUniqueId: (base: string) => string
  makeLinkId: () => string
}): BoardPastePlan {
  const idMap = new Map<string, string>()
  const sourceOrigin = options.snapshot.nodes.reduce(
    (origin, node) => ({
      grid_x: Math.min(origin.grid_x, sanitizeNodeGridUi(node.ui).grid_x),
      grid_y: Math.min(origin.grid_y, sanitizeNodeGridUi(node.ui).grid_y),
    }),
    { grid_x: Number.POSITIVE_INFINITY, grid_y: Number.POSITIVE_INFINITY },
  )
  const anchor = options.anchor || null
  const translateX = anchor ? anchor.grid_x - sourceOrigin.grid_x : options.offset
  const translateY = anchor ? anchor.grid_y - sourceOrigin.grid_y : options.offset
  const newNodes = options.snapshot.nodes.map((node) => {
    const nodeId = options.makeUniqueId(`${String(node.name || node.id || 'node').trim() || 'node'}1`)
    idMap.set(node.id, nodeId)
    return createPastedNodeCard(node, nodeId, translateX, translateY)
  })
  const desired = new Map<string, NodeGridUi>(newNodes.map((node) => [node.id, node.ui]))
  const available = findAvailableGridGroup(desired, options.occupied, options.grid)
  for (const node of newNodes) node.ui = available.get(node.id) || node.ui
  const newLinks: LinkItem[] = []
  const newNodeNotes: NodeNotes = {}
  const sourceNotes = normalizeNodeNotes(options.snapshot.nodeNotes)
  for (const [sourceNodeId, note] of Object.entries(sourceNotes)) {
    const targetNodeId = idMap.get(sourceNodeId)
    if (targetNodeId) newNodeNotes[targetNodeId] = note
  }
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
  return { nodes: newNodes, links: newLinks, idMap, nodeNotes: newNodeNotes }
}

function copyNodeForClipboard(node: NodeCard): NodeCard {
  return {
    id: node.id,
    typeId: node.typeId,
    name: node.name,
    inputNum: node.inputNum,
    outputNum: node.outputNum,
    ui: sanitizeNodeGridUi(node.ui),
    last_message: node.last_message,
    lastRuntimeEvent: null,
    runtimeEvents: [],
    providerId: node.providerId,
    mode: node.mode,
    webSearch: node.webSearch,
    thinking: node.thinking,
    reasoningEffort: node.reasoningEffort,
    instruction: node.instruction,
    systemPrompt: node.systemPrompt,
    plugins: Array.isArray(node.plugins) ? node.plugins.map(String).filter(Boolean) : [],
    tools: Array.isArray(node.tools) ? node.tools.map(String).filter(Boolean) : [],
    mcpServers: Array.isArray(node.mcpServers) ? node.mcpServers.map(String).filter(Boolean) : [],
    workingPath: node.workingPath,
    remoteEnabled: node.remoteEnabled,
    remoteWorkerId: node.remoteWorkerId,
  }
}

function createPastedNodeCard(node: NodeCard, nodeId: string, translateX: number, translateY: number): NodeCard {
  return {
    id: nodeId,
    typeId: node.typeId,
    name: node.name,
    inputNum: node.inputNum,
    outputNum: node.outputNum,
    ui: sanitizeNodeGridUi({
      ...node.ui,
      grid_x: Math.max(0, node.ui.grid_x + translateX),
      grid_y: Math.max(0, node.ui.grid_y + translateY),
    }),
    last_message: null,
    lastRuntimeEvent: null,
    runtimeEvents: [],
    providerId: node.providerId,
    mode: node.mode,
    webSearch: node.webSearch,
    thinking: node.thinking,
    reasoningEffort: node.reasoningEffort,
    instruction: node.instruction,
    systemPrompt: node.systemPrompt,
    plugins: Array.isArray(node.plugins) ? node.plugins.map(String).filter(Boolean) : [],
    tools: Array.isArray(node.tools) ? node.tools.map(String).filter(Boolean) : [],
    mcpServers: Array.isArray(node.mcpServers) ? node.mcpServers.map(String).filter(Boolean) : [],
    workingPath: node.workingPath,
    remoteEnabled: node.remoteEnabled,
    remoteWorkerId: node.remoteWorkerId,
  }
}
