import { describe, expect, it } from 'vitest'
import type { BoardClipboardSnapshot } from '../src/components/agent-board/boardClipboard'
import {
  BOARD_NODES_CLIPBOARD_MIME,
  BOARD_NODES_CLIPBOARD_TEXT_PREFIX,
  classifyBoardPaste,
  createBoardClipboardMarker,
  parseBoardClipboardMarker,
  serializeBoardClipboardMarker,
  writeBoardClipboardMarker,
  type ActiveBoardClipboard,
} from '../src/components/agent-board/boardClipboardProtocol'

class FakeClipboardData {
  private readonly formats = new Map<string, string>()
  items: DataTransferItem[] = []

  get types() {
    return Array.from(this.formats.keys())
  }

  clearData(format?: string) {
    if (format) {
      this.formats.delete(format)
      return
    }
    this.formats.clear()
  }

  getData(format: string) {
    return this.formats.get(format) || ''
  }

  setData(format: string, data: string) {
    this.formats.set(format, data)
  }

  asDataTransfer() {
    return this as unknown as DataTransfer
  }
}

function makeSnapshot(): BoardClipboardSnapshot {
  return {
    graphId: 'graph-a',
    nodes: [{ id: 'node-a' }],
    links: [],
  } as BoardClipboardSnapshot
}

function makeActiveClipboard(token = 'copy-token'): ActiveBoardClipboard {
  const snapshot = makeSnapshot()
  return {
    marker: createBoardClipboardMarker(snapshot, token),
    snapshot,
  }
}

describe('AgentPark board clipboard protocol', () => {
  it('round-trips a strict marker', () => {
    const marker = createBoardClipboardMarker(makeSnapshot(), 'copy-token')

    expect(parseBoardClipboardMarker(serializeBoardClipboardMarker(marker))).toEqual(marker)
  })

  it('replaces previous clipboard formats when nodes are copied', () => {
    const clipboard = new FakeClipboardData()
    clipboard.setData('text/plain', 'old clipboard text')
    clipboard.setData('image/png', 'old image')
    const marker = createBoardClipboardMarker(makeSnapshot(), 'copy-token')

    writeBoardClipboardMarker(clipboard.asDataTransfer(), marker)

    expect(clipboard.types).toEqual([BOARD_NODES_CLIPBOARD_MIME, 'text/plain'])
    expect(clipboard.getData(BOARD_NODES_CLIPBOARD_MIME)).toBe(
      serializeBoardClipboardMarker(marker),
    )
    expect(clipboard.getData('text/plain')).toBe(
      `${BOARD_NODES_CLIPBOARD_TEXT_PREFIX}${serializeBoardClipboardMarker(marker)}`,
    )
  })

  it('pastes nodes only when the system marker matches the active snapshot', () => {
    const clipboard = new FakeClipboardData()
    const active = makeActiveClipboard()
    clipboard.setData(BOARD_NODES_CLIPBOARD_MIME, serializeBoardClipboardMarker(active.marker))
    clipboard.setData('text/plain', 'AgentPark node selection (1 node)')

    const source = classifyBoardPaste(clipboard.asDataTransfer(), active)

    expect(source).toEqual({
      kind: 'board-nodes',
      snapshot: active.snapshot,
    })
  })

  it('recognizes the explicit text representation when a platform strips custom MIME data', () => {
    const clipboard = new FakeClipboardData()
    const active = makeActiveClipboard()
    clipboard.setData(
      'text/plain',
      `${BOARD_NODES_CLIPBOARD_TEXT_PREFIX}${serializeBoardClipboardMarker(active.marker)}`,
    )

    expect(classifyBoardPaste(clipboard.asDataTransfer(), active)).toEqual({
      kind: 'board-nodes',
      snapshot: active.snapshot,
    })
  })

  it('does not let a stale in-memory node snapshot intercept external text', () => {
    const clipboard = new FakeClipboardData()
    clipboard.setData('text/plain', 'new external text')

    expect(classifyBoardPaste(clipboard.asDataTransfer(), makeActiveClipboard())).toEqual({
      kind: 'text',
      text: 'new external text',
    })
  })

  it('does not let a stale in-memory node snapshot intercept external images', () => {
    const clipboard = new FakeClipboardData()
    const image = new File(['image'], 'capture.png', { type: 'image/png' })
    clipboard.items = [
      {
        kind: 'file',
        type: 'image/png',
        getAsFile: () => image,
      } as DataTransferItem,
    ]
    clipboard.setData('text/plain', 'image caption')

    const source = classifyBoardPaste(clipboard.asDataTransfer(), makeActiveClipboard())

    expect(source.kind).toBe('images')
    if (source.kind !== 'images') throw new Error('Expected an image paste source')
    expect(source.files).toEqual([image])
    expect(source.text).toBe('image caption')
  })

  it('reports an expired node marker instead of falling through to text', () => {
    const clipboard = new FakeClipboardData()
    const active = makeActiveClipboard('current-token')
    const expired = createBoardClipboardMarker(makeSnapshot(), 'expired-token')
    clipboard.setData(BOARD_NODES_CLIPBOARD_MIME, serializeBoardClipboardMarker(expired))
    clipboard.setData('text/plain', 'must not become PasteAgent input')

    expect(() => classifyBoardPaste(clipboard.asDataTransfer(), active)).toThrow(
      'snapshot has expired',
    )
  })

  it('rejects unsupported marker versions explicitly', () => {
    const raw = JSON.stringify({
      protocol: 'agentpark.board-nodes',
      version: 99,
      token: 'copy-token',
      sourceGraphId: 'graph-a',
      nodeCount: 1,
    })

    expect(() => parseBoardClipboardMarker(raw)).toThrow(
      'Unsupported AgentPark node clipboard version: 99',
    )
  })
})
