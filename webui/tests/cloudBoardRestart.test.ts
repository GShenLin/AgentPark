import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { restartBoardConnection } from '../src/portal/restartConnection'

function connection(instance: string, post: 'ok' | 'lost' | 'denied' = 'ok') {
  return {
    close: vi.fn(),
    rpc: { http: vi.fn(async (request: Record<string, unknown>) => {
      if (request.method === 'POST' && post === 'lost') throw new Error('Connection closed before reply')
      const denied = request.method === 'POST' && post === 'denied'
      return { status: denied ? 403 : 200, headers: {},
        body: btoa(JSON.stringify(denied ? { detail: 'denied' } : { ok: true, instance_id: instance })) }
    }) },
  }
}
beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('cloud Board update and restart', () => {
  it('waits for a different process over new P2P connections and sends restart only once', async () => {
    const current = connection('before')
    const stillOld = connection('before')
    const restarted = connection('after')
    const reconnect = vi.fn().mockResolvedValueOnce(stillOld).mockResolvedValueOnce(restarted)
    const operation = restartBoardConnection(current, reconnect, vi.fn(), new AbortController().signal)
    await vi.advanceTimersByTimeAsync(2100)
    expect(await operation).toBe(restarted)
    expect(current.rpc.http.mock.calls.filter(([request]) => request.method === 'POST')).toHaveLength(1)
    expect(current.close).toHaveBeenCalledOnce()
    expect(stillOld.close).toHaveBeenCalledOnce()
    expect(restarted.close).not.toHaveBeenCalled()
  })

  it('recovers after a lost acknowledgement without replaying the restart command', async () => {
    const current = connection('before', 'lost')
    const restarted = connection('after')
    const status = vi.fn()
    const operation = restartBoardConnection(current, vi.fn().mockResolvedValue(restarted), status, new AbortController().signal)
    await vi.advanceTimersByTimeAsync(1100)
    expect(await operation).toBe(restarted)
    expect(status).toHaveBeenCalledWith(expect.stringContaining('未收到完整重启回执'))
    expect(current.rpc.http.mock.calls.filter(([request]) => request.method === 'POST')).toHaveLength(1)
  })

  it('reports a rejected restart immediately instead of pretending the device is updating', async () => {
    const reconnect = vi.fn()
    await expect(restartBoardConnection(connection('before', 'denied'), reconnect, vi.fn(), new AbortController().signal))
      .rejects.toThrow('403')
    expect(reconnect).not.toHaveBeenCalled()
  })

  it('stops waiting when the Board is closed', async () => {
    const controller = new AbortController()
    const reconnect = vi.fn()
    const operation = restartBoardConnection(connection('before'), reconnect, vi.fn(), controller.signal)
    const assertion = expect(operation).rejects.toThrow()
    await vi.advanceTimersByTimeAsync(100)
    controller.abort()
    await vi.advanceTimersByTimeAsync(1000)
    await assertion
    expect(reconnect).not.toHaveBeenCalled()
  })

  it('does not call the original process a successful restart when the deadline expires', async () => {
    const reconnect = vi.fn().mockImplementation(async () => connection('before'))
    const operation = restartBoardConnection(connection('before'), reconnect, vi.fn(), new AbortController().signal)
    const assertion = expect(operation).rejects.toThrow('Restart timed out')
    await vi.advanceTimersByTimeAsync(301000)
    await assertion
  })
})
