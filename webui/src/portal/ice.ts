export interface IceLease {
  ice_servers: { urls: string[]; username: string; credential: string }[]
  expires_at: number
}

export function parseIceLease(value: unknown): IceLease {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('云端连接凭证格式无效。')
  const raw = value as Record<string, unknown>
  if (Object.keys(raw).sort().join(',') !== 'expires_at,ice_servers' ||
      !Number.isSafeInteger(raw.expires_at) || Number(raw.expires_at) <= Date.now() / 1000 ||
      !Array.isArray(raw.ice_servers) || raw.ice_servers.length > 4) throw new Error('云端连接凭证无效或已过期，请重新连接。')
  for (const server of raw.ice_servers) {
    if (!server || typeof server !== 'object' || Array.isArray(server) ||
        Object.keys(server).sort().join(',') !== 'credential,urls,username' ||
        typeof server.username !== 'string' || !server.username || server.username.length > 200 ||
        typeof server.credential !== 'string' || !server.credential || server.credential.length > 200 ||
        !Array.isArray(server.urls) || !server.urls.length || server.urls.length > 4) throw new Error('云端中继服务器配置无效。')
    for (const url of server.urls) {
      const match = typeof url === 'string' && /^(turns?):(?:\[[0-9a-fA-F:]+\]|[a-zA-Z0-9.-]+):([0-9]{1,5})\?transport=(tcp|udp)$/.exec(url)
      if (!match || Number(match[2]) < 1 || Number(match[2]) > 65535 ||
          (match[1] === 'turns' && match[3] !== 'tcp')) throw new Error('云端中继地址无效。')
    }
  }
  return raw as unknown as IceLease
}

/** Report the selected ICE pair, never infer the route from configured servers. */
export function connectionLabel(stats: RTCStatsReport): string {
  let pair: RTCIceCandidatePairStats | undefined
  stats.forEach(report => {
    if (report.type === 'transport' && report.selectedCandidatePairId) pair = stats.get(report.selectedCandidatePairId)
  })
  if (!pair) stats.forEach(report => {
    if (report.type === 'candidate-pair' && report.nominated && report.state === 'succeeded') pair = report
  })
  if (!pair) return '已连接（路径待确认）'
  const local = stats.get(pair.localCandidateId)
  const remote = stats.get(pair.remoteCandidateId)
  if (local?.candidateType === 'relay' || remote?.candidateType === 'relay') return '已通过中继连接'
  if (local?.candidateType && remote?.candidateType) return '已直连'
  return '已连接（路径待确认）'
}
