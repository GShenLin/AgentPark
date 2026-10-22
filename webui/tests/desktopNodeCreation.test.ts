import { effectScope, nextTick, ref } from 'vue'
import { afterEach, expect, test, vi } from 'vitest'
import { useDesktopNodeCreation } from '../src/components/agent-board/useDesktopNodeCreation'

afterEach(() => vi.unstubAllGlobals())

test('NewNode waits for bootstrap and consumes the URL action only once', async () => {
  const location = { href: 'http://127.0.0.1:8788/?desktop_action=new-node&keep=1' }
  const replaceState = vi.fn((_state, _unused, url) => { location.href = String(url) })
  vi.stubGlobal('window', { location, history: { state: { test: 1 }, replaceState } })
  const ready = ref(false)
  const board = ref({ getBoundingClientRect: () => ({ left: 20, top: 50, width: 600, height: 500 }) } as HTMLElement)
  const menu = ref({ openAt: vi.fn() })
  const scope = effectScope()
  scope.run(() => useDesktopNodeCreation({ ready: () => ready.value, board, menu, toBoard: p => ({ x: p.x / 2, y: p.y / 2 }) }))
  expect(menu.value.openAt).not.toHaveBeenCalled()
  ready.value = true
  await nextTick()
  expect(menu.value.openAt).toHaveBeenCalledExactlyOnceWith({ x: 320, y: 150 }, { x: 160, y: 75 })
  expect(location.href).toBe('http://127.0.0.1:8788/?keep=1')
  ready.value = false
  await nextTick()
  ready.value = true
  await nextTick()
  expect(menu.value.openAt).toHaveBeenCalledOnce()
  scope.stop()
})
