import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { notifyWorkAlertGraphEvent, useWorkAlerts } from '../src/composables/useWorkAlerts'

const state = useWorkAlerts()

function tip(id: string) {
  return {
    event: 'runtime_notice', source: 'user_interaction', stage: 'user_tip',
    graph_id: 'graph-a', node_instance_id: 'node-a', ts: '2026-09-20T12:00:00Z',
    message: JSON.stringify({ tip_id: id, title: '进度提示', message: '已完成检查，继续执行。' }),
  }
}

beforeEach(() => {
  vi.unstubAllGlobals()
  for (const alert of state.alerts.value) state.dismissWorkAlert(alert.id)
})

afterEach(() => vi.unstubAllGlobals())

describe('Tips shared work alert channel', () => {
  it('queues Tips alongside persisted-work alerts without requiring a response', () => {
    notifyWorkAlertGraphEvent({ event: 'work_persisted_alert', alert_id: 'work-1', node_id: 'node-a' })
    notifyWorkAlertGraphEvent(tip('tip-1'))
    expect(state.alerts.value.map(alert => alert.kind)).toEqual(['work_persisted', 'tip'])
    expect(state.latestAlert.value).toEqual({
      id: 'user-tip:tip-1', kind: 'tip', graphId: 'graph-a', nodeId: 'node-a', nodeName: 'node-a',
      title: '进度提示', message: '已完成检查，继续执行。', createdAt: '2026-09-20T12:00:00Z',
    })
    state.dismissWorkAlert('user-tip:tip-1')
    expect(state.latestAlert.value?.kind).toBe('work_persisted')
  })

  it('deduplicates delivery and ignores snapshots and malformed notices', () => {
    const event = tip('tip-2')
    notifyWorkAlertGraphEvent({ ...event, stream_snapshot: true })
    notifyWorkAlertGraphEvent({ ...event, message: '{invalid JSON' })
    notifyWorkAlertGraphEvent({ ...event, message: JSON.stringify({ tip_id: 'bad', message: 'missing title' }) })
    notifyWorkAlertGraphEvent({ ...event, source: 'unrelated' })
    expect(state.alerts.value).toHaveLength(0)
    notifyWorkAlertGraphEvent(event)
    notifyWorkAlertGraphEvent(event)
    expect(state.alerts.value).toHaveLength(1)
  })

  it('preserves long text and treats HTML-like text as notification data', () => {
    const message = '<button>这只是文本</button>\n'.repeat(200)
    notifyWorkAlertGraphEvent({
      ...tip('tip-3'), message: JSON.stringify({ tip_id: 'tip-3', title: '提示', message }),
    })
    expect(state.latestAlert.value?.message).toBe(message)
  })

  it('retains ordinary ask_user alerts and ignores completed interactions', () => {
    const event = {
      ...tip('unused'), stage: 'user_interaction_created',
      message: JSON.stringify({ request_id: 'request-1', title: '请选择方案' }),
    }
    notifyWorkAlertGraphEvent({ ...event, stage: 'user_interaction_submitted' })
    expect(state.alerts.value).toHaveLength(0)
    notifyWorkAlertGraphEvent(event)
    expect(state.latestAlert.value).toMatchObject({ kind: 'user_interaction', title: '需要你的确认', message: '请选择方案' })
  })

  it('uses the same desktop notification delivery when permission is granted', () => {
    const delivered: { title: string, options: NotificationOptions }[] = []
    class FakeNotification {
      static permission = 'granted'
      constructor(title: string, options: NotificationOptions) { delivered.push({ title, options }) }
    }
    vi.stubGlobal('Notification', FakeNotification)
    vi.stubGlobal('window', { matchMedia: () => ({ matches: false }) })
    notifyWorkAlertGraphEvent(tip('tip-4'))
    expect(delivered).toEqual([{
      title: 'node-a · graph-a', options: { body: '已完成检查，继续执行。', tag: 'user-tip:tip-4' },
    }])
  })
})
