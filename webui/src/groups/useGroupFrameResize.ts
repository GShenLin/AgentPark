import { onBeforeUnmount, ref, watch, toRaw, type Ref } from 'vue'
import type { AgentGroup, GroupBounds } from './groupApi'
import type { BoardGridSettings } from '../components/agent-board/boardGrid'
import { resizeGroupBounds, type ResizeEdge } from './groupGeometry'
import type { BoardGroups } from './useBoardGroups'

export function useGroupFrameResize(state: BoardGroups, grid: Ref<BoardGridSettings>,
  point: (event: MouseEvent) => { x: number; y: number }) {
  const preview = ref<{ id: string; bounds: GroupBounds } | null>(null)
  let drag: { group: AgentGroup; edge: ResizeEdge; x: number; y: number; pointer: number;
    element: HTMLElement; grid: BoardGridSettings; moved: boolean } | null = null
  function clear() {
    const previous = drag
    drag = null
    if (previous?.element.hasPointerCapture(previous.pointer)) previous.element.releasePointerCapture(previous.pointer)
    preview.value = null
  }
  function start(event: PointerEvent, group: AgentGroup, edge: ResizeEdge) {
    if (event.button !== 0 || state.busy.value || !state.ready.value) return
    event.preventDefault()
    clear()
    const p = point(event)
    const element = event.currentTarget as HTMLElement
    drag = { group: structuredClone(toRaw(group)), edge, ...p, pointer: event.pointerId, element,
      grid: { ...grid.value }, moved: false }
    preview.value = { id: group.id, bounds: { ...group.bounds } }
    element.setPointerCapture(event.pointerId)
  }
  function move(event: PointerEvent) {
    if (!drag || drag.pointer !== event.pointerId) return
    const p = point(event)
    drag.moved ||= Math.abs(p.x - drag.x) + Math.abs(p.y - drag.y) > 3
    preview.value = { id: drag.group.id,
      bounds: resizeGroupBounds(drag.group.bounds, drag.edge, p.x - drag.x, p.y - drag.y, drag.grid) }
  }
  async function finish(event: PointerEvent) {
    if (!drag || drag.pointer !== event.pointerId) return
    move(event)
    const { group, moved } = drag
    const bounds = preview.value!.bounds
    clear()
    if (moved && JSON.stringify(bounds) !== JSON.stringify(group.bounds)) await state.resize(group, bounds)
  }
  function onKey(event: KeyboardEvent) { if (event.key === 'Escape') clear() }
  watch([state.graphId, state.ready, grid], clear)
  window.addEventListener('keydown', onKey)
  window.addEventListener('blur', clear)
  onBeforeUnmount(() => { clear(); window.removeEventListener('keydown', onKey); window.removeEventListener('blur', clear) })
  return { preview, start, move, finish, cancel: clear }
}
