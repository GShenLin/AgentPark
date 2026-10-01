import { beforeEach, describe, expect, it, vi } from 'vitest'
vi.mock('../src/api', () => ({ waitForRemoteWorker: vi.fn() }))
import { waitForRemoteWorker } from '../src/api'
import { ensureBoundRemoteWorkerOnline } from '../src/remoteWorkerConnection'

describe('registered remote binding', () => {
  beforeEach(() => vi.clearAllMocks())
  it('waits for the exact saved device without browser-local discovery', async () => {
    const worker = { worker_id: 'peer:host:remote', display_name: 'Remote PC', host_kind: 'standalone', workspace_path: 'D:/Workspace', capabilities: ['read_file'], online: true }
    vi.mocked(waitForRemoteWorker).mockResolvedValue({ ok: true, worker })
    expect((await ensureBoundRemoteWorkerOnline(worker.worker_id)).worker).toEqual(worker)
    expect(waitForRemoteWorker).toHaveBeenCalledExactlyOnceWith(worker.worker_id, 5)
  })
  it('reports offline and authorization failures without choosing another device', async () => {
    vi.mocked(waitForRemoteWorker).mockRejectedValue(new Error('Device offline'))
    await expect(ensureBoundRemoteWorkerOnline('bound-worker')).rejects.toThrow('Device offline')
    expect(waitForRemoteWorker).toHaveBeenCalledTimes(1)
  })
  it('requires explicit node binding', async () => {
    await expect(ensureBoundRemoteWorkerOnline(' ')).rejects.toThrow('LinkToRemote')
    expect(waitForRemoteWorker).not.toHaveBeenCalled()
  })
})
