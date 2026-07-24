import { computed, ref } from 'vue'

export type WorkAlert = {
  id: string
  kind: 'work_persisted' | 'user_interaction' | 'runtime_event'
  graphId: string
  nodeId: string
  nodeName: string
  title: string
  message: string
  createdAt: string
}

export type WorkAlertNavigationRequest = {
  graphId: string
  nodeId: string
  nonce: number
}

const alerts = ref<WorkAlert[]>([])
const navigationRequest = ref<WorkAlertNavigationRequest | null>(null)
const audioReady = ref(false)
const notificationPermission = ref<NotificationPermission>(
  typeof Notification === 'undefined' ? 'denied' : Notification.permission,
)
const seenAlertIds = new Set<string>()
const MAX_VISIBLE_ALERTS = 20
const MOBILE_QUERY = '(max-width: 760px)'

let audioContext: AudioContext | null = null
let foregroundCleanup: (() => void) | null = null
let navigationNonce = 0

function isMobileViewport() {
  return typeof window !== 'undefined' && window.matchMedia(MOBILE_QUERY).matches
}

function getAudioContext() {
  if (audioContext) return audioContext
  const AudioContextConstructor = window.AudioContext
  audioContext = new AudioContextConstructor()
  return audioContext
}

export async function enableWorkAlertAudio() {
  if (typeof window === 'undefined' || typeof window.AudioContext === 'undefined') return false
  try {
    const context = getAudioContext()
    if (context.state === 'suspended') await context.resume()
    audioReady.value = context.state === 'running'
    return audioReady.value
  } catch {
    audioReady.value = false
    return false
  }
}

async function playWorkAlertTone() {
  if (!(await enableWorkAlertAudio())) return
  const context = getAudioContext()
  const start = context.currentTime
  const gain = context.createGain()
  gain.gain.setValueAtTime(0.0001, start)
  gain.gain.exponentialRampToValueAtTime(0.22, start + 0.02)
  gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.55)
  gain.connect(context.destination)

  for (const [offset, frequency] of [[0, 660], [0.16, 880]] as const) {
    const oscillator = context.createOscillator()
    oscillator.type = 'sine'
    oscillator.frequency.setValueAtTime(frequency, start + offset)
    oscillator.connect(gain)
    oscillator.start(start + offset)
    oscillator.stop(start + offset + 0.28)
  }
}

export async function enableDesktopNotifications() {
  if (typeof Notification === 'undefined') return 'denied' as NotificationPermission
  if (Notification.permission === 'default') {
    notificationPermission.value = await Notification.requestPermission()
  } else {
    notificationPermission.value = Notification.permission
  }
  return notificationPermission.value
}

function showDesktopNotification(alert: WorkAlert) {
  if (isMobileViewport() || typeof Notification === 'undefined' || Notification.permission !== 'granted') return
  const notification = new Notification(`${alert.nodeName} · ${alert.graphId}`, {
    body: alert.message || alert.title,
    tag: alert.id,
  })
  notification.onclick = () => {
    window.focus()
    activateWorkAlert(alert)
    notification.close()
  }
}

function parseInteractionNotice(payload: Record<string, unknown>) {
  if (
    String(payload.event || '').trim() !== 'runtime_notice' ||
    String(payload.source || '').trim() !== 'user_interaction' ||
    String(payload.stage || '').trim() !== 'user_interaction_created'
  ) {
    return null
  }
  try {
    const value = JSON.parse(String(payload.message || '{}')) as unknown
    return value && typeof value === 'object' ? value as Record<string, unknown> : null
  } catch {
    return null
  }
}

function normalizeAlert(payload: Record<string, unknown>): WorkAlert | null {
  if (payload.stream_snapshot === true) return null
  const eventName = String(payload.event || '').trim()
  const graphId = String(payload.graph_id || '').trim() || 'default'
  if (eventName === 'work_persisted_alert') {
    const nodeId = String(payload.node_instance_id || payload.node_id || '').trim()
    if (!nodeId) return null
    const traceId = String(payload.trace_id || '').trim()
    const id = String(payload.alert_id || '').trim() || `work-persisted:${graphId}:${nodeId}:${traceId || payload.version || ''}`
    return {
      id,
      kind: 'work_persisted',
      graphId,
      nodeId,
      nodeName: String(payload.node_name || '').trim() || nodeId,
      title: String(payload.title || '').trim() || '工作已落盘',
      message: String(payload.message || '').trim(),
      createdAt: String(payload.ts || '').trim(),
    }
  }

  if (eventName === 'runtime_event_notice') {
    const nodeId = String(payload.node_instance_id || payload.node_id || '').trim()
    if (!nodeId) return null
    const runtimeEvent = String(payload.runtime_event || '').trim()
    const traceId = String(payload.trace_id || '').trim()
    const id = String(payload.alert_id || '').trim()
      || `runtime-event:${graphId}:${nodeId}:${runtimeEvent}:${traceId || payload.version || ''}`
    return {
      id,
      kind: 'runtime_event',
      graphId,
      nodeId,
      nodeName: String(payload.node_name || '').trim() || nodeId,
      title: String(payload.title || '').trim() || '事件已触发',
      message: String(payload.message || '').trim() || (runtimeEvent ? `${runtimeEvent} 已触发。` : '节点事件已触发。'),
      createdAt: String(payload.ts || '').trim(),
    }
  }

  const notice = parseInteractionNotice(payload)
  if (!notice) return null
  const requestId = String(notice.request_id || '').trim()
  if (!requestId) return null
  const nodeId = String(notice.node_id || payload.node_instance_id || payload.node_id || '').trim()
  const nodeName = String(notice.node_name || payload.node_name || '').trim() || nodeId || 'Agent'
  const description = String(notice.description || '').trim()
  return {
    id: `user-interaction:${requestId}`,
    kind: 'user_interaction',
    graphId: String(notice.graph_id || '').trim() || graphId,
    nodeId,
    nodeName,
    title: '需要你的确认',
    message: String(notice.title || '').trim() || description || 'Agent 发起了一条确认请求。',
    createdAt: String(payload.ts || '').trim(),
  }
}

export function notifyWorkAlertGraphEvent(payload: Record<string, unknown>) {
  const alert = normalizeAlert(payload)
  if (!alert || seenAlertIds.has(alert.id)) return
  seenAlertIds.add(alert.id)
  alerts.value = [...alerts.value, alert].slice(-MAX_VISIBLE_ALERTS)
  void playWorkAlertTone()
  showDesktopNotification(alert)
}

export function dismissWorkAlert(alertId: string) {
  alerts.value = alerts.value.filter((alert) => alert.id !== alertId)
}

export function activateWorkAlert(alert: WorkAlert) {
  if (alert.kind !== 'work_persisted') return false
  const graphId = String(alert.graphId || '').trim()
  const nodeId = String(alert.nodeId || '').trim()
  if (!graphId || !nodeId) return false
  navigationRequest.value = {
    graphId,
    nodeId,
    nonce: ++navigationNonce,
  }
  dismissWorkAlert(alert.id)
  return true
}

export function completeWorkAlertNavigation(nonce: number) {
  if (navigationRequest.value?.nonce === nonce) navigationRequest.value = null
}

export function initializeForegroundAlerts() {
  if (foregroundCleanup || typeof window === 'undefined') return foregroundCleanup || (() => undefined)
  const prime = () => {
    void enableWorkAlertAudio()
  }
  window.addEventListener('pointerdown', prime, { once: true, passive: true })
  window.addEventListener('keydown', prime, { once: true })
  foregroundCleanup = () => {
    window.removeEventListener('pointerdown', prime)
    window.removeEventListener('keydown', prime)
    foregroundCleanup = null
  }
  return foregroundCleanup
}

export function useWorkAlerts() {
  return {
    alerts: computed(() => alerts.value),
    latestAlert: computed(() => alerts.value[alerts.value.length - 1] || null),
    navigationRequest: computed(() => navigationRequest.value),
    audioReady: computed(() => audioReady.value),
    notificationPermission: computed(() => notificationPermission.value),
    dismissWorkAlert,
    activateWorkAlert,
    completeWorkAlertNavigation,
    enableWorkAlertAudio,
    enableDesktopNotifications,
  }
}
