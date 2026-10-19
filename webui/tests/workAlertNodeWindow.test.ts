import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { initializeWorkAlertFocus, usesNativeWorkAlerts } from '../src/workAlertNodeWindow'

const api = vi.hoisted(() => ({ base: '' }))
vi.mock('../src/api', () => ({ getActiveApiBase: () => api.base }))

class Socket {
  static OPEN = 1
  static instances: Socket[] = []
  readyState = 0
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  closed = false
  constructor(readonly url: URL) { Socket.instances.push(this) }
  send(value: string) { this.sent.push(value) }
  open() { this.readyState = 1; this.onopen?.() }
  close() { this.closed = true; this.readyState = 3; this.onclose?.() }
}
let page: EventTarget & { visibilityState: string; hasFocus: () => boolean }
let browser: EventTarget & Record<string, any>
let focused: boolean
let cleanup: (() => void) | undefined

beforeEach(() => {
  vi.useFakeTimers()
  api.base = ''
  Socket.instances = []
  focused = true
  page = Object.assign(new EventTarget(), { visibilityState: 'visible', hasFocus: () => focused })
  browser = Object.assign(new EventTarget(), {
    location: { href: 'http://127.0.0.1:8765/' }, matchMedia: () => ({ matches: false }),
  })
  vi.stubGlobal('window', browser)
  vi.stubGlobal('document', page)
  vi.stubGlobal('navigator', { platform: 'Win32' })
  vi.stubGlobal('WebSocket', Socket)
})
afterEach(() => { cleanup?.(); cleanup = undefined; vi.useRealTimers(); vi.unstubAllGlobals() })

it('reports focus to the backend and releases the connection when the browser page closes', () => {
  cleanup = initializeWorkAlertFocus()
  const socket = Socket.instances[0]!
  expect(socket.url.href).toBe('ws://127.0.0.1:8765/api/desktop/node-windows/focus')
  socket.open()
  expect(socket.sent).toEqual(['{"focused":true}'])
  focused = false
  browser.dispatchEvent(new Event('blur'))
  expect(socket.sent.at(-1)).toBe('{"focused":false}')
  focused = true
  browser.dispatchEvent(new Event('focus'))
  expect(socket.sent.at(-1)).toBe('{"focused":true}')
  browser.dispatchEvent(new Event('pagehide'))
  expect(socket.closed).toBe(true)
  vi.advanceTimersByTime(30000)
  expect(Socket.instances).toHaveLength(1)
})

it('reports hidden tabs as unfocused and reconnects after page restoration', () => {
  cleanup = initializeWorkAlertFocus()
  Socket.instances[0]!.open()
  page.visibilityState = 'hidden'
  page.dispatchEvent(new Event('visibilitychange'))
  expect(Socket.instances[0]!.sent.at(-1)).toBe('{"focused":false}')
  browser.dispatchEvent(new Event('pagehide'))
  browser.dispatchEvent(new Event('pageshow'))
  Socket.instances[1]!.open()
  expect(Socket.instances[1]!.sent).toEqual(['{"focused":false}'])
})

it('reconnects after backend restart and cancels retry on unmount', () => {
  cleanup = initializeWorkAlertFocus()
  Socket.instances[0]!.open()
  Socket.instances[0]!.close()
  vi.advanceTimersByTime(1000)
  expect(Socket.instances).toHaveLength(2)
  Socket.instances[1]!.open()
  expect(Socket.instances[1]!.sent).toEqual(['{"focused":true}'])
  Socket.instances[1]!.close()
  cleanup()
  vi.advanceTimersByTime(30000)
  expect(Socket.instances).toHaveLength(2)
})

it('includes focused detached windows even when their viewport is small', () => {
  browser.agentParkNodeWindow = { target: { nodeId: 'n', graphId: 'g' } }
  browser.matchMedia = () => ({ matches: true })
  expect(usesNativeWorkAlerts()).toBe(true)
  cleanup = initializeWorkAlertFocus()
  Socket.instances[0]!.open()
  expect(Socket.instances[0]!.sent).toEqual(['{"focused":true}'])
})

it.each([
  ['remote site', 'https://agent.example/', '', 'Win32', false],
  ['remote API', 'http://127.0.0.1:8765/', 'http://192.168.1.2:8765', 'Win32', false],
  ['other local service', 'http://127.0.0.1:8765/', 'http://127.0.0.1:9999', 'Win32', false],
  ['non-Windows', 'http://127.0.0.1:8765/', '', 'Linux x86_64', false],
  ['mobile', 'http://127.0.0.1:8765/', '', 'Win32', true],
])('does not report %s as a local foreground page', (_label, href, base, platform, mobile) => {
  browser.location.href = href
  browser.matchMedia = () => ({ matches: mobile })
  api.base = base
  vi.stubGlobal('navigator', { platform })
  expect(usesNativeWorkAlerts()).toBe(false)
  cleanup = initializeWorkAlertFocus()
  expect(Socket.instances).toHaveLength(0)
})
