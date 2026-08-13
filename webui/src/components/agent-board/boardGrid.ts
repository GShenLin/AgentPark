export const DEFAULT_GRID_CELL_WIDTH = 300
export const DEFAULT_GRID_CELL_HEIGHT = 320
export const MIN_GRID_CELL_WIDTH = 230
export const MIN_GRID_CELL_HEIGHT = 250
export const MAX_GRID_CELL_SIZE = 2000
export const DEFAULT_GRID_COLUMNS = 4
export const DEFAULT_NODE_WIDTH = 230
export const DEFAULT_NODE_HEIGHT = 250
export const MIN_NODE_WIDTH = 50
export const MIN_NODE_HEIGHT = 50
export const MAX_NODE_WIDTH = 720
export const MAX_NODE_HEIGHT = 760
export const MIN_NODE_RENDER_SIZE = 1

export type BoardGridSettings = { cellWidth: number; cellHeight: number }
export type BoardLayoutDefaults = BoardGridSettings & { nodeWidth: number; nodeHeight: number }
export type NodeGridPosition = { grid_x: number; grid_y: number }
export type NodeGridUi = NodeGridPosition & { width?: number; height?: number }

export function normalizeBoardLayoutDefaults(value: unknown): BoardLayoutDefaults {
  const root = isRecord(value) ? value : {}
  const settings = isRecord(root.boardLayout) ? root.boardLayout : root
  return {
    cellWidth: boundedInteger(settings.gridCellWidth, DEFAULT_GRID_CELL_WIDTH, MIN_GRID_CELL_WIDTH, MAX_GRID_CELL_SIZE),
    cellHeight: boundedInteger(settings.gridCellHeight, DEFAULT_GRID_CELL_HEIGHT, MIN_GRID_CELL_HEIGHT, MAX_GRID_CELL_SIZE),
    nodeWidth: boundedInteger(settings.nodeWidth, DEFAULT_NODE_WIDTH, MIN_NODE_WIDTH, MAX_NODE_WIDTH),
    nodeHeight: boundedInteger(settings.nodeHeight, DEFAULT_NODE_HEIGHT, MIN_NODE_HEIGHT, MAX_NODE_HEIGHT),
  }
}

export function boardGridSettingsFromDefaults(defaults: BoardLayoutDefaults): BoardGridSettings {
  return { cellWidth: defaults.cellWidth, cellHeight: defaults.cellHeight }
}

export function normalizeBoardGridSettings(layout: unknown): BoardGridSettings {
  const value = isRecord(layout) ? layout : {}
  const grid = isRecord(value.grid) ? value.grid : {}
  return {
    cellWidth: boundedInteger(grid.cell_width, DEFAULT_GRID_CELL_WIDTH, MIN_GRID_CELL_WIDTH, MAX_GRID_CELL_SIZE),
    cellHeight: boundedInteger(grid.cell_height, DEFAULT_GRID_CELL_HEIGHT, MIN_GRID_CELL_HEIGHT, MAX_GRID_CELL_SIZE),
  }
}

export function serializeBoardGridSettings(settings: BoardGridSettings) {
  return {
    grid: {
      cell_width: boundedInteger(settings.cellWidth, DEFAULT_GRID_CELL_WIDTH, MIN_GRID_CELL_WIDTH, MAX_GRID_CELL_SIZE),
      cell_height: boundedInteger(settings.cellHeight, DEFAULT_GRID_CELL_HEIGHT, MIN_GRID_CELL_HEIGHT, MAX_GRID_CELL_SIZE),
    },
  }
}

export function sanitizeNodeGridUi(value: unknown): NodeGridUi {
  if (!isRecord(value)) throw new Error('Node ui must be an object.')
  if (!Object.prototype.hasOwnProperty.call(value, 'grid_x') || !Object.prototype.hasOwnProperty.call(value, 'grid_y')) {
    throw new Error('Node ui.grid_x and ui.grid_y are required.')
  }
  const width = value.width == null ? undefined : boundedInteger(value.width, MIN_NODE_RENDER_SIZE, MIN_NODE_RENDER_SIZE, MAX_GRID_CELL_SIZE)
  const height = value.height == null ? undefined : boundedInteger(value.height, MIN_NODE_RENDER_SIZE, MIN_NODE_RENDER_SIZE, MAX_GRID_CELL_SIZE)
  return {
    grid_x: nonNegativeInteger(value.grid_x, 'ui.grid_x'),
    grid_y: nonNegativeInteger(value.grid_y, 'ui.grid_y'),
    ...(width == null ? {} : { width }),
    ...(height == null ? {} : { height }),
  }
}

export function gridPositionToBoardPoint(position: NodeGridPosition, settings: BoardGridSettings) {
  return { x: position.grid_x * settings.cellWidth, y: position.grid_y * settings.cellHeight }
}

export function boardPointToGridPosition(point: { x: number; y: number }, settings: BoardGridSettings): NodeGridPosition {
  return {
    grid_x: Math.max(0, Math.round(Number(point.x || 0) / settings.cellWidth)),
    grid_y: Math.max(0, Math.round(Number(point.y || 0) / settings.cellHeight)),
  }
}

export function nodeGridSpan(ui: Pick<NodeGridUi, 'width' | 'height'>, settings: BoardGridSettings) {
  const width = Number.isFinite(Number(ui.width)) ? Number(ui.width) : DEFAULT_NODE_WIDTH
  const height = Number.isFinite(Number(ui.height)) ? Number(ui.height) : DEFAULT_NODE_HEIGHT
  return {
    spanX: Math.max(1, Math.ceil(width / settings.cellWidth)),
    spanY: Math.max(1, Math.ceil(height / settings.cellHeight)),
  }
}

export function gridRectangleCellKeys(position: NodeGridPosition, spanX = 1, spanY = 1) {
  const keys = new Set<string>()
  for (let y = position.grid_y; y < position.grid_y + Math.max(1, spanY); y += 1) {
    for (let x = position.grid_x; x < position.grid_x + Math.max(1, spanX); x += 1) keys.add(`${x}:${y}`)
  }
  return keys
}

export function occupiedGridCellKeys(
  nodes: Array<{ id: string; ui: NodeGridUi }>,
  settings: BoardGridSettings,
  excludeIds: Iterable<string> = [],
) {
  const excluded = new Set(excludeIds)
  const occupied = new Set<string>()
  for (const node of nodes) {
    if (excluded.has(node.id)) continue
    const { spanX, spanY } = nodeGridSpan(node.ui, settings)
    for (const key of gridRectangleCellKeys(node.ui, spanX, spanY)) occupied.add(key)
  }
  return occupied
}

export function findAvailableGridOrigin(
  occupied: Set<string>,
  ui: Pick<NodeGridUi, 'width' | 'height'>,
  settings: BoardGridSettings,
  preferred?: NodeGridPosition | null,
): NodeGridPosition {
  const { spanX, spanY } = nodeGridSpan(ui, settings)
  const available = (position: NodeGridPosition) => (
    Array.from(gridRectangleCellKeys(position, spanX, spanY)).every((key) => !occupied.has(key))
  )
  if (!preferred) {
    for (let index = 0; ; index += 1) {
      const candidate = { grid_x: index % DEFAULT_GRID_COLUMNS, grid_y: Math.floor(index / DEFAULT_GRID_COLUMNS) }
      if (available(candidate)) return candidate
    }
  }
  const preferredX = Math.max(0, Math.round(preferred.grid_x))
  const preferredY = Math.max(0, Math.round(preferred.grid_y))
  for (const offset of nearestGridOffsets(settings)) {
    const candidate = { grid_x: preferredX + offset.x, grid_y: preferredY + offset.y }
    if (candidate.grid_x >= 0 && candidate.grid_y >= 0 && available(candidate)) return candidate
  }
  throw new Error('Failed to find an available grid origin.')
}

export function findAvailableGridGroup(
  desired: Map<string, NodeGridUi>,
  occupied: Set<string>,
  settings: BoardGridSettings,
): Map<string, NodeGridUi> {
  const entries = Array.from(desired.entries())
  if (!entries.length) return new Map()
  for (const offset of nearestGridOffsets(settings)) {
      const candidate = new Map<string, NodeGridUi>()
      const reserved = new Set<string>()
      let valid = true
      for (const [id, ui] of entries) {
        const next = { ...ui, grid_x: ui.grid_x + offset.x, grid_y: ui.grid_y + offset.y }
        if (next.grid_x < 0 || next.grid_y < 0) {
          valid = false
          break
        }
        const { spanX, spanY } = nodeGridSpan(next, settings)
        const keys = gridRectangleCellKeys(next, spanX, spanY)
        if (Array.from(keys).some((key) => occupied.has(key) || reserved.has(key))) {
          valid = false
          break
        }
        for (const key of keys) reserved.add(key)
        candidate.set(id, next)
      }
      if (valid) return candidate
  }
  throw new Error('Failed to find an available grid group.')
}

function* nearestGridOffsets(settings: BoardGridSettings): Generator<{ x: number; y: number }> {
  type QueueEntry = { score: number; x: number; y: number }
  const queue: QueueEntry[] = [{ score: 0, x: 0, y: 0 }]
  const queued = new Set(['0:0'])
  while (queue.length) {
    const current = heapPop(queue)
    if (!current) return
    yield { x: current.x, y: current.y }
    for (const next of [
      { x: current.x - 1, y: current.y },
      { x: current.x + 1, y: current.y },
      { x: current.x, y: current.y - 1 },
      { x: current.x, y: current.y + 1 },
    ]) {
      const key = `${next.x}:${next.y}`
      if (queued.has(key)) continue
      queued.add(key)
      heapPush(queue, {
        ...next,
        score: (next.x * settings.cellWidth) ** 2 + (next.y * settings.cellHeight) ** 2,
      })
    }
  }
}

function compareQueueEntry(a: { score: number; x: number; y: number }, b: { score: number; x: number; y: number }) {
  return a.score - b.score || a.y - b.y || a.x - b.x
}

function heapPush<T extends { score: number; x: number; y: number }>(heap: T[], value: T) {
  heap.push(value)
  let index = heap.length - 1
  while (index > 0) {
    const parent = Math.floor((index - 1) / 2)
    if (compareQueueEntry(heap[parent]!, heap[index]!) <= 0) break
    ;[heap[parent], heap[index]] = [heap[index]!, heap[parent]!]
    index = parent
  }
}

function heapPop<T extends { score: number; x: number; y: number }>(heap: T[]): T | undefined {
  const first = heap[0]
  const last = heap.pop()
  if (!first || !last || heap.length === 0) return first
  heap[0] = last
  let index = 0
  while (true) {
    const left = index * 2 + 1
    const right = left + 1
    let smallest = index
    if (left < heap.length && compareQueueEntry(heap[left]!, heap[smallest]!) < 0) smallest = left
    if (right < heap.length && compareQueueEntry(heap[right]!, heap[smallest]!) < 0) smallest = right
    if (smallest === index) break
    ;[heap[index], heap[smallest]] = [heap[smallest]!, heap[index]!]
    index = smallest
  }
  return first
}

function boundedInteger(value: unknown, fallback: number, minimum: number, maximum: number) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.max(minimum, Math.min(maximum, Math.round(parsed)))
}

function nonNegativeInteger(value: unknown, field: string) {
  const parsed = Number(value)
  if (!Number.isInteger(parsed) || parsed < 0) throw new Error(`${field} must be a non-negative integer.`)
  return parsed
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}
