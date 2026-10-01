import { getActiveApiBase, requestApiJson, type RemoteWorker } from './api'

export type RegisteredRemoteWorker = RemoteWorker & {
  connection_kind: 'direct' | 'coordinator'
  host_peer_id?: string
}

export async function listRemoteWorkers(): Promise<RegisteredRemoteWorker[]> {
  const result = await requestApiJson(getActiveApiBase(), '/api/remote-workers')
  return result.workers as RegisteredRemoteWorker[]
}
