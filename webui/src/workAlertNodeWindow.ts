import { getActiveApiBase } from './api'

function isLocalDesktop() {
  if (typeof window === 'undefined' || typeof document === 'undefined'
    || typeof navigator === 'undefined' || !window.location) return false
  if (!navigator.platform.startsWith('Win')) return false
  if (!window.agentParkNodeWindow && window.matchMedia('(max-width: 760px)').matches) return false
  const page = new URL(window.location.href)
  const api = new URL(getActiveApiBase() || page.origin, page.origin)
  return page.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(page.hostname)
    && api.origin === page.origin && api.pathname === '/' && !api.search && !api.hash
}

/** Native delivery belongs to the backend, including when no browser is running. */
export function usesNativeWorkAlerts() {
  return isLocalDesktop()
}

/** Each page reports focus over a connection that is released when the browser exits. */
export function initializeWorkAlertFocus() {
  if (!isLocalDesktop()) return () => undefined
  let socket: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | null = null
  let disposed = false
  let suspended = false
  let retryDelay = 1000
  const report = () => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ focused: document.visibilityState === 'visible' && document.hasFocus() }))
    }
  }
  const connect = () => {
    if (disposed || suspended || socket || !isLocalDesktop()) return
    const url = new URL('/api/desktop/node-windows/focus', window.location.href)
    url.protocol = 'ws:'
    const current = new WebSocket(url)
    socket = current
    current.onopen = () => {
      if (socket !== current) return
      retryDelay = 1000
      report()
    }
    current.onerror = () => console.error('AgentPark 页面焦点连接失败，后台可能无法判断当前页面是否在前台。')
    current.onclose = () => {
      if (socket !== current) return
      socket = null
      if (!disposed && !suspended) {
        retry = setTimeout(() => { retry = null; connect() }, retryDelay)
        retryDelay = Math.min(retryDelay * 2, 10000)
      }
    }
  }
  const disconnect = () => {
    if (retry !== null) clearTimeout(retry)
    retry = null
    const current = socket
    socket = null
    current?.close()
  }
  const update = () => { connect(); report() }
  const hide = () => { suspended = true; disconnect() }
  const show = () => { suspended = false; update() }
  window.addEventListener('focus', update)
  window.addEventListener('blur', report)
  window.addEventListener('pagehide', hide)
  window.addEventListener('pageshow', show)
  document.addEventListener('visibilitychange', report)
  connect()
  return () => {
    disposed = true
    disconnect()
    window.removeEventListener('focus', update)
    window.removeEventListener('blur', report)
    window.removeEventListener('pagehide', hide)
    window.removeEventListener('pageshow', show)
    document.removeEventListener('visibilitychange', report)
  }
}
