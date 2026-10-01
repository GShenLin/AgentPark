import { waitForRemoteWorker, type RemoteWorker } from './api'

export async function ensureBoundRemoteWorkerOnline(workerId: string): Promise<{ ok: boolean; worker: RemoteWorker }> {
  const id = workerId.trim()
  if (!id) throw new Error('请先通过 LinkToRemote 为节点选择远程设备。')
  // A saved binding never depends on the browser-local companion.
  return waitForRemoteWorker(id, 5)
}
