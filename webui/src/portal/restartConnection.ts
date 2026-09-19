import { decodeBase64 } from './crypto'
import type { BrowserPeerRpc } from './rpc'
import { waitForRestart, type ServerStatus } from '../utils/serverRestart'

export interface BoardConnection {
  rpc: Pick<BrowserPeerRpc, 'http'>
  close(): void
}

class BoardHttpError extends Error {}

async function readStatus(connection: BoardConnection, method: 'GET' | 'POST', path: string): Promise<ServerStatus> {
  const reply = await connection.rpc.http({ method, path, headers: {}, body: '' })
  const text = new TextDecoder().decode(decodeBase64(reply.body))
  if (reply.status < 200 || reply.status >= 300) {
    throw new BoardHttpError(`设备拒绝了${method === 'POST' ? '重启' : '状态'}请求（${reply.status}）：${text}`)
  }
  const status = JSON.parse(text)
  if (status.ok !== true || typeof status.instance_id !== 'string' || !status.instance_id) {
    throw new Error('设备返回的重启状态缺少有效进程编号。')
  }
  return status
}

/** Send the update/restart command once, then observe a new backend process over fresh P2P links. */
export async function restartBoardConnection<T extends BoardConnection>(
  current: T,
  reconnect: (signal: AbortSignal) => Promise<T>,
  onStatus: (message: string) => void,
  signal: AbortSignal,
): Promise<T> {
  const previous = await readStatus(current, 'GET', '/api/system/status')
  signal.throwIfAborted()
  onStatus('正在请求设备拉取更新并重启…')
  try {
    await readStatus(current, 'POST', '/api/system/restart')
    onStatus('设备已接受重启请求，等待更新完成并重新连接…')
  } catch (cause) {
    // A rejected HTTP request did not authorize a restart. A lost reply is
    // ambiguous, so observe process identity without replaying the command.
    if (cause instanceof BoardHttpError) throw cause
    onStatus(`未收到完整重启回执，正在检查设备是否已重启：${String(cause)}`)
  }
  current.close()
  let recovered: T | undefined
  try {
    await waitForRestart(previous.instance_id, async (pollSignal) => {
      signal.throwIfAborted()
      const combinedSignal = AbortSignal.any([signal, pollSignal])
      const candidate = await reconnect(combinedSignal)
      const close = () => candidate.close()
      combinedSignal.addEventListener('abort', close, { once: true })
      let keep = false
      try {
        combinedSignal.throwIfAborted()
        const status = await readStatus(candidate, 'GET', '/api/system/status')
        if (status.instance_id !== previous.instance_id) {
          recovered = candidate
          keep = true
        }
        return status
      } finally { combinedSignal.removeEventListener('abort', close); if (!keep) candidate.close() }
    }, 300_000, { signal, pollTimeoutMs: 45_000 })
    if (!recovered) throw new Error('未能确认设备的新进程。')
    signal.throwIfAborted()
    return recovered
  } catch (cause) {
    recovered?.close()
    throw cause
  }
}
