import type { NodeWindowBridge, NodeWindowResizeEdge } from './nodeWindow'

export function createNodeWindowResize(host: Pick<NodeWindowBridge, 'beginResize' | 'moveResize' | 'endResize'>) {
  let session: { id: number; element: Element } | null = null
  function cancel() {
    if (!session) return
    const previous = session
    session = null
    host.endResize()
    if (previous.element.hasPointerCapture(previous.id)) previous.element.releasePointerCapture(previous.id)
  }
  function down(edge: NodeWindowResizeEdge, event: PointerEvent) {
    if (event.button !== 0 || !event.isPrimary || !(event.currentTarget instanceof Element)) return
    event.preventDefault()
    event.stopPropagation()
    cancel()
    session = { id: event.pointerId, element: event.currentTarget }
    session.element.setPointerCapture(session.id)
    host.beginResize(edge)
  }
  function move(event: PointerEvent) {
    if (!session || session.id !== event.pointerId) return
    event.preventDefault()
    host.moveResize()
  }
  function up(event: PointerEvent) {
    if (session?.id === event.pointerId) cancel()
  }
  return { down, move, up, cancel }
}
