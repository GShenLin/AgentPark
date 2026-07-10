import type { PointerDragDelta } from './pointerDrag'

export type EdgeResizeHandle = 'right' | 'left' | 'bottom' | 'bottom-right' | 'bottom-left'

export type EdgeResizeSession = {
  handle: EdgeResizeHandle
  startWidth: number
  startHeight: number
}

export type EdgeResizeBounds = {
  minWidth: number
  maxWidth: number
  minHeight: number
  maxHeight: number
}

export function clampResizeValue(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

export function edgeResizeCursor(handle: EdgeResizeHandle) {
  if (handle === 'bottom') return 'ns-resize'
  if (handle === 'left' || handle === 'right') return 'ew-resize'
  if (handle === 'bottom-left') return 'nesw-resize'
  return 'nwse-resize'
}

export function edgeResizeSize(session: EdgeResizeSession, delta: PointerDragDelta, bounds: EdgeResizeBounds) {
  let nextWidth = session.startWidth
  let nextHeight = session.startHeight

  if (session.handle === 'right' || session.handle === 'bottom-right') {
    nextWidth = session.startWidth + delta.dx
  } else if (session.handle === 'left' || session.handle === 'bottom-left') {
    nextWidth = session.startWidth - delta.dx
  }

  if (session.handle === 'bottom' || session.handle === 'bottom-right' || session.handle === 'bottom-left') {
    nextHeight = session.startHeight + delta.dy
  }

  return {
    width: clampResizeValue(nextWidth, bounds.minWidth, bounds.maxWidth),
    height: clampResizeValue(nextHeight, bounds.minHeight, bounds.maxHeight),
  }
}
