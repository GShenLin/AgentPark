import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../src/api', async importOriginal => {
  const actual = await importOriginal<typeof import('../src/api')>()
  return {
    ...actual,
    discoverLocalRemoteWorker: vi.fn(),
    pairRemoteWorker: vi.fn(),
    waitForRemoteWorker: vi.fn(),
  }
})

import {
  ApiHttpError,
  discoverLocalRemoteWorker,
  pairRemoteWorker,
  waitForRemoteWorker,
} from '../src/api'
import {
  ensureBoundRemoteWorkerOnline,
  pairLocalRemoteWorker,
} from '../src/remoteWorkerConnection'

const worker = {
  worker_id: 'bound-worker',
  display_name: 'Remote PC',
  host_kind: 'standalone',
  workspace_path: 'D:\\Workspace',
  capabilities: ['read_file'],
  online: true,
}

describe('remote worker connection orchestration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses the bound worker immediately when it is online', async () => {
    vi.mocked(waitForRemoteWorker).mockResolvedValue({ ok: true, worker })

    await expect(ensureBoundRemoteWorkerOnline('bound-worker')).resolves.toEqual({ ok: true, worker })

    expect(waitForRemoteWorker).toHaveBeenCalledOnce()
    expect(waitForRemoteWorker).toHaveBeenCalledWith('bound-worker', 0.5)
    expect(discoverLocalRemoteWorker).not.toHaveBeenCalled()
  })

  it('wakes the local companion and waits for the same bound worker', async () => {
    vi.mocked(waitForRemoteWorker)
      .mockRejectedValueOnce(new ApiHttpError(409, 'offline'))
      .mockResolvedValueOnce({ ok: true, worker })
    vi.mocked(discoverLocalRemoteWorker).mockResolvedValue({
      ok: true,
      server_url: 'http://192.168.34.15:8788',
    })

    await expect(ensureBoundRemoteWorkerOnline('bound-worker')).resolves.toEqual({ ok: true, worker })

    expect(discoverLocalRemoteWorker).toHaveBeenCalledOnce()
    expect(waitForRemoteWorker).toHaveBeenNthCalledWith(1, 'bound-worker', 0.5)
    expect(waitForRemoteWorker).toHaveBeenNthCalledWith(2, 'bound-worker', 6)
    expect(pairRemoteWorker).not.toHaveBeenCalled()
  })

  it('does not turn unrelated HTTP failures into reconnect attempts', async () => {
    vi.mocked(waitForRemoteWorker).mockRejectedValue(new ApiHttpError(403, 'forbidden'))

    await expect(ensureBoundRemoteWorkerOnline('bound-worker')).rejects.toThrow('HTTP 403: forbidden')

    expect(discoverLocalRemoteWorker).not.toHaveBeenCalled()
  })

  it('pairs only after local discovery and retries typed not-found responses', async () => {
    vi.stubGlobal('window', { setTimeout })
    vi.mocked(discoverLocalRemoteWorker).mockResolvedValue({
      ok: true,
      server_url: 'http://192.168.34.15:8788',
    })
    vi.mocked(pairRemoteWorker)
      .mockRejectedValueOnce(new ApiHttpError(404, 'not registered yet'))
      .mockResolvedValueOnce({ ok: true, worker })

    await expect(pairLocalRemoteWorker()).resolves.toEqual({ ok: true, worker })

    expect(discoverLocalRemoteWorker).toHaveBeenCalledOnce()
    expect(pairRemoteWorker).toHaveBeenCalledTimes(2)
    vi.unstubAllGlobals()
  })
})
