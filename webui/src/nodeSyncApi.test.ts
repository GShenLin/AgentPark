import { describe, expect, it } from 'vitest'
import { sameSyncSelection, needsSyncUsername, syncRemoteLabel } from './nodeSyncApi'

describe('sync preview selection identity', () => {
  it('survives sorted server JSON keys and distinguishes scope and endpoint changes', () => {
    const browser = { remote_id: 'remote-a', graph_id: 'graph-a', node_id: 'Agent' }
    const persisted = { graph_id: 'graph-a', node_id: 'Agent', remote_id: 'remote-a' }
    expect(sameSyncSelection(browser, persisted)).toBe(true)
    expect(sameSyncSelection(browser, { ...persisted, node_id: null })).toBe(false)
    expect(sameSyncSelection(browser, { ...persisted, remote_id: 'remote-b' })).toBe(false)
    expect(sameSyncSelection(browser, { ...persisted, graph_id: 'graph-b' })).toBe(false)
  })
  it('distinguishes cloud devices from LAN identity and labels without invented host addresses', () => {
    expect(needsSyncUsername('default')).toBe(false)
    expect(needsSyncUsername('office')).toBe(true)
    expect(needsSyncUsername('cloud:server:device')).toBe(false)
    expect(syncRemoteLabel({ id: 'cloud:server:device', name: '开发电脑', kind: 'cloud',
      address: 'https://example.test', available: true, state: '在线' })).toBe('开发电脑 · 远程设备 · 在线')
  })
})
