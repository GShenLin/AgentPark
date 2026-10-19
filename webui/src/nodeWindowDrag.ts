import type { NodeWindowBridge } from './nodeWindow'

/** Keep ordinary node clicks and button actions; only a deliberate drag moves the OS window. */
export function createNodeWindowDrag(host: Pick<NodeWindowBridge, 'beginDrag' | 'moveDrag' | 'endDrag'>) {
  let session: { id: number; x: number; y: number; element: Element; moved: boolean } | null = null
  let suppressClick = false
  const controls = 'button, input, textarea, select, a, summary, video, audio, [contenteditable], [role="button"], [data-node-window-interactive]'
  function down(event: PointerEvent) {
    if (event.button !== 0 || !event.isPrimary || !(event.target instanceof Element)) return
    cancel()
    suppressClick = false
    if (event.target.closest(controls)) return
    session = { id: event.pointerId, x: event.screenX, y: event.screenY, element: event.target, moved: false }
    event.target.setPointerCapture(event.pointerId)
    host.beginDrag()
  }
  function move(event: PointerEvent) {
    if (!session || event.pointerId !== session.id) return
    if (!session.moved && Math.hypot(event.screenX - session.x, event.screenY - session.y) < 4) return
    session.moved = true
    event.preventDefault()
    host.moveDrag()
  }
  function cancel() {
    if (!session) return
    const previous = session
    session = null
    suppressClick = previous.moved
    host.endDrag()
    if (previous.element.hasPointerCapture(previous.id)) previous.element.releasePointerCapture(previous.id)
  }
  function up(event: PointerEvent) {
    if (session?.id === event.pointerId) cancel()
  }
  function click(event: MouseEvent) {
    if (!suppressClick || event.detail === 0) return
    suppressClick = false
    event.preventDefault()
    event.stopImmediatePropagation()
  }
  return { down, move, up, cancel, click }
}
