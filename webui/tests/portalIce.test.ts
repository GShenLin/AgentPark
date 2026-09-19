import { describe, expect, it } from 'vitest'
import { connectionLabel, parseIceLease } from '../src/portal/ice'

describe('authenticated ICE configuration', () => {
  const lease = () => ({ expires_at: Math.floor(Date.now() / 1000) + 60,
    ice_servers: [{ urls: ['turn:example.com:3478?transport=tcp'], username: 'temporary-user', credential: 'temporary-key' }] })
  it('accepts temporary TURN credentials and rejects stale or malformed configuration', () => {
    expect(parseIceLease(lease()).ice_servers).toHaveLength(1)
    expect(() => parseIceLease({ ...lease(), expires_at: 1 })).toThrow('过期')
    expect(() => parseIceLease({ ...lease(), extra: true })).toThrow()
    const invalid = lease()
    invalid.ice_servers[0]!.urls = ['turns:example.com:5349?transport=udp']
    expect(() => parseIceLease(invalid)).toThrow('地址无效')
  })
  it('reports the selected candidate pair, including a remote relay', () => {
    const stats = new Map([
      ['transport', { type: 'transport', selectedCandidatePairId: 'selected' }],
      ['selected', { type: 'candidate-pair', localCandidateId: 'local', remoteCandidateId: 'remote' }],
      ['local', { type: 'local-candidate', candidateType: 'host' }],
      ['remote', { type: 'remote-candidate', candidateType: 'relay' }],
    ]) as unknown as RTCStatsReport
    expect(connectionLabel(stats)).toBe('已通过中继连接')
    stats.get('remote').candidateType = 'srflx'
    expect(connectionLabel(stats)).toBe('已直连')
    expect(connectionLabel(new Map() as unknown as RTCStatsReport)).toContain('路径待确认')
  })
})
