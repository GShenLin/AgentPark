import type { Ref } from 'vue'

export type PointerDragDelta = {
  dx: number
  dy: number
  clientDx: number
  clientDy: number
  scale: number
}

export type PointerDragEnd = {
  clientX: number
  clientY: number
  pointerEvent: PointerEvent | null
}

export type PointerDragStartOptions = {
  cursor?: string
  preventDefault?: boolean
  stopPropagation?: boolean
  userSelect?: string
}

export function createWindowPointerDrag<T>(options: {
  session: Ref<T | null>
  getPointerId: (session: T) => number
  getScale?: () => number
  cursor?: string | ((session: T) => string)
  userSelect?: string
  onMove: (event: PointerEvent, delta: PointerDragDelta, session: T) => void
  onEnd?: (end: PointerDragEnd, session: T) => void
}) {
  let startClientX = 0
  let startClientY = 0
  let lastClientX = 0
  let lastClientY = 0
  let previousCursor = ''
  let previousUserSelect = ''

  function scaleValue() {
    return Math.max(options.getScale?.() || 1, 0.01)
  }

  function resolveCursor(session: T, override?: string) {
    if (override) return override
    return typeof options.cursor === 'function' ? options.cursor(session) : options.cursor || ''
  }

  function removeListeners() {
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', onPointerUp)
    window.removeEventListener('pointercancel', onPointerUp)
    window.removeEventListener('blur', onBlur)
  }

  function restoreBodyDragStyle() {
    document.body.style.cursor = previousCursor
    document.body.style.userSelect = previousUserSelect
  }

  function stop(event?: PointerEvent | Event) {
    const session = options.session.value
    if (!session) return
    options.session.value = null
    removeListeners()
    restoreBodyDragStyle()
    const pointerEvent = event instanceof PointerEvent ? event : null
    if (pointerEvent) {
      lastClientX = pointerEvent.clientX
      lastClientY = pointerEvent.clientY
    }
    options.onEnd?.({ clientX: lastClientX, clientY: lastClientY, pointerEvent }, session)
  }

  function onPointerMove(event: PointerEvent) {
    const session = options.session.value
    if (!session || event.pointerId !== options.getPointerId(session)) return
    lastClientX = event.clientX
    lastClientY = event.clientY
    const scale = scaleValue()
    const clientDx = event.clientX - startClientX
    const clientDy = event.clientY - startClientY
    options.onMove(
      event,
      {
        dx: clientDx / scale,
        dy: clientDy / scale,
        clientDx,
        clientDy,
        scale,
      },
      session,
    )
    if (event.cancelable) event.preventDefault()
  }

  function onPointerUp(event: PointerEvent) {
    const session = options.session.value
    if (!session || event.pointerId !== options.getPointerId(session)) return
    stop(event)
  }

  function onBlur(event: Event) {
    stop(event)
  }

  function start(session: T, event: PointerEvent, startOptions: PointerDragStartOptions = {}) {
    stop()
    options.session.value = session
    startClientX = event.clientX
    startClientY = event.clientY
    lastClientX = event.clientX
    lastClientY = event.clientY
    previousCursor = document.body.style.cursor
    previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = resolveCursor(session, startOptions.cursor)
    document.body.style.userSelect = startOptions.userSelect ?? options.userSelect ?? 'none'
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    window.addEventListener('pointercancel', onPointerUp)
    window.addEventListener('blur', onBlur)
    if (startOptions.preventDefault && event.cancelable) event.preventDefault()
    if (startOptions.stopPropagation) event.stopPropagation()
  }

  return {
    start,
    stop,
  }
}
