import { nextTick, ref } from 'vue'

type Position = { top: number; following: boolean; anchor?: string; offset?: number }

/** Newest-first activity: keep the visible event anchored while new items arrive. */
export function useGroupScroll() {
  const body = ref<HTMLElement | null>(null)
  const following = ref(true)
  function onScroll() {
    if (body.value) following.value = body.value.scrollTop < 32
  }
  function capture(): Position {
    const el = body.value
    const position: Position = { top: el?.scrollTop || 0, following: following.value }
    if (!el || !el.clientHeight) return position
    const top = el.getBoundingClientRect().top
    const anchor = [...el.querySelectorAll<HTMLElement>('[data-event-seq]')]
      .find(item => item.getBoundingClientRect().bottom > top)
    if (anchor) { position.anchor = anchor.dataset.eventSeq; position.offset = anchor.getBoundingClientRect().top - top }
    return position
  }
  async function restore(position: Position, force = false) {
    await nextTick()
    const el = body.value
    if (!el) return
    if (force || position.following) { el.scrollTop = 0; following.value = true; return }
    const anchor = position.anchor ? el.querySelector<HTMLElement>(`[data-event-seq="${position.anchor}"]`) : null
    el.scrollTop = anchor ? el.scrollTop + anchor.getBoundingClientRect().top - el.getBoundingClientRect().top - (position.offset || 0) : position.top
    following.value = false
  }
  async function latest() { await restore({ top: 0, following: true }, true) }
  return { body, following, onScroll, capture, restore, latest }
}
