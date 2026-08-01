import type { BoardClipboardSnapshot } from './boardClipboard'

export const BOARD_NODES_CLIPBOARD_MIME = 'application/x-agentpark-board-nodes'
export const BOARD_NODES_CLIPBOARD_TEXT_PREFIX = 'AgentParkClipboard:'

const BOARD_CLIPBOARD_PROTOCOL = 'agentpark.board-nodes'
const BOARD_CLIPBOARD_VERSION = 1

export type BoardClipboardMarker = {
  protocol: typeof BOARD_CLIPBOARD_PROTOCOL
  version: typeof BOARD_CLIPBOARD_VERSION
  token: string
  sourceGraphId: string
  nodeCount: number
}

export type ActiveBoardClipboard = {
  marker: BoardClipboardMarker
  snapshot: BoardClipboardSnapshot
}

export type BoardPasteSource =
  | {
      kind: 'board-nodes'
      snapshot: BoardClipboardSnapshot
    }
  | {
      kind: 'images'
      files: File[]
      text: string
    }
  | {
      kind: 'text'
      text: string
    }
  | {
      kind: 'empty'
    }

export function createBoardClipboardMarker(
  snapshot: BoardClipboardSnapshot,
  token: string,
): BoardClipboardMarker {
  const safeToken = String(token || '').trim()
  if (!safeToken) throw new Error('AgentPark node clipboard token is empty.')
  if (!snapshot.nodes.length) throw new Error('AgentPark node clipboard snapshot has no nodes.')
  return {
    protocol: BOARD_CLIPBOARD_PROTOCOL,
    version: BOARD_CLIPBOARD_VERSION,
    token: safeToken,
    sourceGraphId: String(snapshot.graphId || 'default').trim() || 'default',
    nodeCount: snapshot.nodes.length,
  }
}

export function serializeBoardClipboardMarker(marker: BoardClipboardMarker) {
  return JSON.stringify(marker)
}

export function parseBoardClipboardMarker(raw: string): BoardClipboardMarker {
  let value: unknown
  try {
    value = JSON.parse(String(raw || ''))
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    throw new Error(`AgentPark node clipboard marker is invalid JSON: ${reason}`)
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('AgentPark node clipboard marker must be an object.')
  }

  const marker = value as Record<string, unknown>
  if (marker.protocol !== BOARD_CLIPBOARD_PROTOCOL) {
    throw new Error('AgentPark node clipboard protocol is invalid.')
  }
  if (marker.version !== BOARD_CLIPBOARD_VERSION) {
    throw new Error(`Unsupported AgentPark node clipboard version: ${String(marker.version)}`)
  }

  const token = String(marker.token || '').trim()
  const sourceGraphId = String(marker.sourceGraphId || '').trim()
  const nodeCount = Number(marker.nodeCount)
  if (!token) throw new Error('AgentPark node clipboard token is missing.')
  if (!sourceGraphId) throw new Error('AgentPark node clipboard source graph is missing.')
  if (!Number.isInteger(nodeCount) || nodeCount <= 0) {
    throw new Error('AgentPark node clipboard node count must be a positive integer.')
  }

  return {
    protocol: BOARD_CLIPBOARD_PROTOCOL,
    version: BOARD_CLIPBOARD_VERSION,
    token,
    sourceGraphId,
    nodeCount,
  }
}

export function writeBoardClipboardMarker(
  clipboardData: DataTransfer | null,
  marker: BoardClipboardMarker,
) {
  if (!clipboardData) {
    throw new Error('The system clipboard is unavailable for copying AgentPark nodes.')
  }
  clipboardData.clearData()
  const serialized = serializeBoardClipboardMarker(marker)
  clipboardData.setData(BOARD_NODES_CLIPBOARD_MIME, serialized)
  clipboardData.setData('text/plain', `${BOARD_NODES_CLIPBOARD_TEXT_PREFIX}${serialized}`)
}

export function hasBoardClipboardMarker(clipboardData: DataTransfer | null) {
  if (!clipboardData) return false
  const hasMime = Array.from(clipboardData.types || []).some(
    (type) => String(type || '').toLowerCase() === BOARD_NODES_CLIPBOARD_MIME,
  )
  if (hasMime) return true
  return String(clipboardData.getData('text/plain') || '').startsWith(
    BOARD_NODES_CLIPBOARD_TEXT_PREFIX,
  )
}

export function readBoardClipboardMarker(
  clipboardData: DataTransfer | null,
): BoardClipboardMarker | null {
  if (!clipboardData || !hasBoardClipboardMarker(clipboardData)) return null
  const hasMime = Array.from(clipboardData.types || []).some(
    (type) => String(type || '').toLowerCase() === BOARD_NODES_CLIPBOARD_MIME,
  )
  const raw = hasMime
    ? clipboardData.getData(BOARD_NODES_CLIPBOARD_MIME)
    : String(clipboardData.getData('text/plain') || '').slice(
        BOARD_NODES_CLIPBOARD_TEXT_PREFIX.length,
      )
  if (!String(raw || '').trim()) {
    throw new Error('AgentPark node clipboard marker is empty.')
  }
  return parseBoardClipboardMarker(raw)
}

export function clipboardImageFiles(clipboardData: DataTransfer | null) {
  const imageItems = Array.from(clipboardData?.items || []).filter(
    (item) => item.kind === 'file' && item.type.toLowerCase().startsWith('image/'),
  )
  if (!imageItems.length) return []

  const files = imageItems
    .map((item) => item.getAsFile())
    .filter((file): file is File => file instanceof File)
  if (files.length !== imageItems.length) {
    throw new Error('One or more pasted images could not be read from the system clipboard.')
  }
  return files
}

export function classifyBoardPaste(
  clipboardData: DataTransfer | null,
  activeClipboard: ActiveBoardClipboard | null,
): BoardPasteSource {
  if (!clipboardData) return { kind: 'empty' }

  const marker = readBoardClipboardMarker(clipboardData)
  if (marker) {
    if (!activeClipboard) {
      throw new Error('The copied AgentPark nodes are no longer available. Copy them again.')
    }
    if (activeClipboard.marker.token !== marker.token) {
      throw new Error('The AgentPark node clipboard snapshot has expired. Copy the nodes again.')
    }
    if (activeClipboard.marker.sourceGraphId !== marker.sourceGraphId) {
      throw new Error('The AgentPark node clipboard source graph does not match the active snapshot.')
    }
    if (
      activeClipboard.marker.nodeCount !== marker.nodeCount
      || activeClipboard.snapshot.nodes.length !== marker.nodeCount
    ) {
      throw new Error('The AgentPark node clipboard node count does not match the active snapshot.')
    }
    return {
      kind: 'board-nodes',
      snapshot: activeClipboard.snapshot,
    }
  }

  const text = String(clipboardData.getData('text/plain') || '')
  const files = clipboardImageFiles(clipboardData)
  if (files.length) {
    return {
      kind: 'images',
      files,
      text,
    }
  }
  if (text.trim()) {
    return {
      kind: 'text',
      text,
    }
  }
  return { kind: 'empty' }
}
