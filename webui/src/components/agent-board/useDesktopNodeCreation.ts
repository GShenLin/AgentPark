import { watch, type Ref } from 'vue'

type Point = { x: number; y: number }
type CreationMenu = { openAt: (screen: Point, board: Point) => void }

/** Consume a tray deep link only after the board and its node catalog are ready. */
export function useDesktopNodeCreation(options: {
  ready: () => boolean
  board: Ref<HTMLElement | null>
  menu: Ref<CreationMenu | null>
  toBoard: (point: Point) => Point
}) {
  watch(
    () => [options.ready(), options.board.value, options.menu.value] as const,
    ([ready, board, menu]) => {
      if (!ready || !board || !menu) return
      const url = new URL(window.location.href)
      if (url.searchParams.get('desktop_action') !== 'new-node') return
      const bounds = board.getBoundingClientRect()
      const point = { x: bounds.left + bounds.width / 2, y: bounds.top + Math.min(100, bounds.height / 2) }
      menu.openAt(point, options.toBoard(point))
      url.searchParams.delete('desktop_action')
      window.history.replaceState(window.history.state, '', url)
    },
    { immediate: true, flush: 'post' },
  )
}
