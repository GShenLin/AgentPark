import { describe, expect, it, vi } from 'vitest'
import { createBoardSession } from '../src/portal/boardSession'
import { captureBoardRequest, resumeBoardRequests, suspendBoardRequests } from '../src/portal/boardRequests'

describe('retained Board connection lifecycle', () => {
  it('suspends listeners and restores access/data before activating streams', async () => {
    const session = createBoardSession()
    const events: string[] = []
    for (const name of ['access', 'chat']) session.register({
      suspend: () => { events.push(`pause:${name}`) },
      restore: async () => { events.push(`restore:${name}`) },
      activate: () => { events.push(`start:${name}`) },
    })
    session.suspend()
    await session.restore()
    expect(events).toEqual(['pause:access', 'pause:chat', 'restore:access', 'restore:chat', 'start:access', 'start:chat'])
    expect(session.phase.value).toBe('ready')
  })

  it('does not reactivate an obsolete restoration after another disconnect', async () => {
    const session = createBoardSession()
    let finish!: () => void
    const activate = vi.fn()
    session.register({ suspend: vi.fn(), restore: () => new Promise(resolve => { finish = resolve }), activate })
    const pending = session.restore()
    session.suspend()
    finish()
    await expect(pending).rejects.toThrow('连接已变化')
    expect(activate).not.toHaveBeenCalled()
    expect(session.phase.value).toBe('offline')
  })

  it('blocks activation on access or destination failure and supports retry', async () => {
    const session = createBoardSession()
    const activate = vi.fn()
    const restore = vi.fn().mockRejectedValueOnce(new Error('node inaccessible')).mockResolvedValue(undefined)
    session.register({ suspend: vi.fn(), restore, activate })
    await expect(session.restore()).rejects.toThrow('node inaccessible')
    expect(activate).not.toHaveBeenCalled()
    expect(session.phase.value).toBe('offline')
    await session.restore()
    expect(activate).toHaveBeenCalledOnce()
  })

  it('aborts old reads, rejects late replies and never queues interrupted writes', () => {
    resumeBoardRequests()
    const read = captureBoardRequest()
    const write = captureBoardRequest({ method: 'POST' })
    suspendBoardRequests()
    expect(read.signal?.aborted).toBe(true)
    expect(() => captureBoardRequest()).toThrow('连接已断开')
    resumeBoardRequests()
    expect(() => read.check()).toThrow('旧连接')
    expect(() => write.check()).toThrow('不会自动重复提交')
    expect(captureBoardRequest().signal?.aborted).toBe(false)
    suspendBoardRequests()
  })
})
