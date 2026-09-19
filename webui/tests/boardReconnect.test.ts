import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'

const hooks = vi.hoisted(() => ({ mount: [] as (() => void)[], unmount: [] as (() => void)[] }))
vi.mock('vue', async original => ({
  ...await original<typeof import('vue')>(),
  onMounted: (fn: () => void) => hooks.mount.push(fn),
  onUnmounted: (fn: () => void) => hooks.unmount.push(fn),
}))
import { useBoardReconnect } from '../src/portal/useBoardReconnect'

let scope: ReturnType<typeof effectScope>
let page: EventTarget & { visibilityState: string }
let browser: EventTarget
beforeEach(() => {
  page = Object.assign(new EventTarget(), { visibilityState: 'visible' })
  browser = new EventTarget()
  vi.stubGlobal('document', page)
  vi.stubGlobal('window', browser)
  scope = effectScope()
})
afterEach(() => {
  hooks.unmount.splice(0).forEach(fn => fn())
  scope.stop()
  vi.unstubAllGlobals()
})
function mount() {
  const ready = ref(true)
  const canReconnect = vi.fn(() => true)
  const reconnect = vi.fn(async () => {})
  const onError = vi.fn()
  scope.run(() => useBoardReconnect({ ready, canReconnect, reconnect, onError }))
  hooks.mount.splice(0).forEach(fn => fn())
  return { ready, canReconnect, reconnect, onError }
}
describe('Board automatic reconnection', () => {
  it('tries once after disconnection and reports a failed attempt without a retry loop', async () => {
    const connection = mount()
    connection.reconnect.mockRejectedValue(new Error('offline'))
    connection.ready.value = false
    await nextTick()
    await nextTick()
    expect(connection.reconnect).toHaveBeenCalledOnce()
    expect(connection.onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'offline' }))
  })
  it('waits while backgrounded and deduplicates resume and online events', async () => {
    const connection = mount()
    let finish!: () => void
    connection.reconnect.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    page.visibilityState = 'hidden'
    connection.ready.value = false
    await nextTick()
    expect(connection.reconnect).not.toHaveBeenCalled()
    page.visibilityState = 'visible'
    page.dispatchEvent(new Event('visibilitychange'))
    browser.dispatchEvent(new Event('online'))
    browser.dispatchEvent(new Event('pageshow'))
    expect(connection.reconnect).toHaveBeenCalledOnce()
    finish()
    await nextTick()
  })
  it('does not interfere with a healthy connection, login, restart, or an existing connection attempt', async () => {
    const connection = mount()
    page.dispatchEvent(new Event('visibilitychange'))
    expect(connection.reconnect).not.toHaveBeenCalled()
    connection.canReconnect.mockReturnValue(false)
    connection.ready.value = false
    await nextTick()
    browser.dispatchEvent(new Event('online'))
    expect(connection.reconnect).not.toHaveBeenCalled()
  })
  it('removes resume listeners when the portal is closed', async () => {
    const connection = mount()
    hooks.unmount.splice(0).forEach(fn => fn())
    connection.ready.value = false
    await nextTick()
    page.dispatchEvent(new Event('visibilitychange'))
    browser.dispatchEvent(new Event('online'))
    expect(connection.reconnect).not.toHaveBeenCalled()
  })
})
