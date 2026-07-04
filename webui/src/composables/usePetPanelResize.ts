import { computed, onBeforeUnmount, ref, type Ref } from 'vue'

import type { NodeDesktopViewPanelSize } from '../api'

export type PetPanelResizeHandle =
  | 'top'
  | 'right'
  | 'bottom'
  | 'left'
  | 'top-left'
  | 'top-right'
  | 'bottom-right'
  | 'bottom-left'

type ResizeSession = {
  pointerId: number
  handle: PetPanelResizeHandle
  startScreenX: number
  startScreenY: number
  startWidth: number
  startHeight: number
  latestSize: NodeDesktopViewPanelSize
}

type PetPanelResizeOptions = {
  viewId: string
  panelElement: Ref<HTMLElement | null>
  panelSize: Ref<NodeDesktopViewPanelSize | null>
  syncPetWindowLayout: (override?: {
    expanded?: boolean
    panelSize?: NodeDesktopViewPanelSize | null
    resizeAnchor?: string
  }) => Promise<unknown>
  persistPanelSize: (size: NodeDesktopViewPanelSize) => Promise<unknown>
}

const MIN_PANEL_WIDTH = 280
const MIN_PANEL_HEIGHT = 220

function clampPanelMinimum(value: number, min: number) {
  return Math.max(min, Math.round(value))
}

export function normalizePetPanelSize(value: unknown): NodeDesktopViewPanelSize | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Record<string, unknown>
  const width = Number(raw.width)
  const height = Number(raw.height)
  if (!Number.isFinite(width) || !Number.isFinite(height)) return null
  return {
    width: clampPanelMinimum(width, MIN_PANEL_WIDTH),
    height: clampPanelMinimum(height, MIN_PANEL_HEIGHT),
  }
}

function resizeCursor(handle: PetPanelResizeHandle) {
  if (handle === 'left' || handle === 'right') return 'ew-resize'
  if (handle === 'top' || handle === 'bottom') return 'ns-resize'
  if (handle === 'top-left' || handle === 'bottom-right') return 'nwse-resize'
  return 'nesw-resize'
}

function measuredPanelSize(element: HTMLElement | null, fallback: NodeDesktopViewPanelSize | null): NodeDesktopViewPanelSize {
  if (element) {
    const rect = element.getBoundingClientRect()
    if (Number.isFinite(rect.width) && Number.isFinite(rect.height) && rect.width > 0 && rect.height > 0) {
      return normalizePetPanelSize({ width: rect.width, height: rect.height }) || { width: 340, height: 360 }
    }
  }
  return fallback || { width: 340, height: 360 }
}

function nextSizeForDrag(session: ResizeSession, event: PointerEvent): NodeDesktopViewPanelSize {
  const deltaX = event.screenX - session.startScreenX
  const deltaY = event.screenY - session.startScreenY
  const growsLeft = session.handle.includes('left')
  const growsRight = session.handle.includes('right')
  const growsTop = session.handle.includes('top')
  const growsBottom = session.handle.includes('bottom')
  const widthDelta = growsLeft ? -deltaX : growsRight ? deltaX : 0
  const heightDelta = growsTop ? -deltaY : growsBottom ? deltaY : 0
  return {
    width: clampPanelMinimum(session.startWidth + widthDelta, MIN_PANEL_WIDTH),
    height: clampPanelMinimum(session.startHeight + heightDelta, MIN_PANEL_HEIGHT),
  }
}

export function usePetPanelResize(options: PetPanelResizeOptions) {
  const resizeSession = ref<ResizeSession | null>(null)
  const isResizingPanel = computed(() => resizeSession.value !== null)
  const panelStyle = computed(() => {
    const size = options.panelSize.value
    if (!size) return {}
    return {
      width: `${size.width}px`,
      height: `${size.height}px`,
    }
  })

  function finishPanelResize(target: EventTarget | null) {
    const session = resizeSession.value
    if (!session) return
    if (target instanceof HTMLElement && typeof target.releasePointerCapture === 'function') {
      try {
        target.releasePointerCapture(session.pointerId)
      } catch {
        // Pointer capture can already be gone after the window changes size.
      }
    }
    resizeSession.value = null
    window.removeEventListener('pointermove', onPanelResizeMove)
    window.removeEventListener('pointerup', onPanelResizeUp)
    document.body.style.cursor = ''
    void options.persistPanelSize(session.latestSize)
    void options.syncPetWindowLayout({ expanded: true, panelSize: session.latestSize })
  }

  function onPanelResizeMove(event: PointerEvent) {
    const session = resizeSession.value
    if (!session || event.pointerId !== session.pointerId) return
    event.preventDefault()
    const nextSize = nextSizeForDrag(session, event)
    session.latestSize = nextSize
    options.panelSize.value = nextSize
    void options.syncPetWindowLayout({
      expanded: true,
      panelSize: nextSize,
      resizeAnchor: session.handle,
    })
  }

  function onPanelResizeUp(event: PointerEvent) {
    const session = resizeSession.value
    if (!session || event.pointerId !== session.pointerId) return
    finishPanelResize(event.target)
  }

  function startPanelResize(handle: PetPanelResizeHandle, event: PointerEvent) {
    if (!options.viewId || event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()
    const startSize = measuredPanelSize(options.panelElement.value, options.panelSize.value)
    resizeSession.value = {
      pointerId: event.pointerId,
      handle,
      startScreenX: event.screenX,
      startScreenY: event.screenY,
      startWidth: startSize.width,
      startHeight: startSize.height,
      latestSize: startSize,
    }
    options.panelSize.value = startSize
    if (event.currentTarget instanceof HTMLElement && typeof event.currentTarget.setPointerCapture === 'function') {
      event.currentTarget.setPointerCapture(event.pointerId)
    }
    document.body.style.cursor = resizeCursor(handle)
    window.addEventListener('pointermove', onPanelResizeMove)
    window.addEventListener('pointerup', onPanelResizeUp)
  }

  onBeforeUnmount(() => {
    resizeSession.value = null
    window.removeEventListener('pointermove', onPanelResizeMove)
    window.removeEventListener('pointerup', onPanelResizeUp)
    document.body.style.cursor = ''
  })

  return {
    isResizingPanel,
    panelStyle,
    startPanelResize,
  }
}
