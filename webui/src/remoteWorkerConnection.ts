import { waitForRemoteWorker, type RemoteWorker } from './api'

export async function ensureBoundRemoteWorkerOnline(workerId: string): Promise<{ ok: boolean; worker: RemoteWorker }> {
  const id = workerId.trim()
  if (!id) throw new Error('请先通过 LinkToRemote 为节点选择远程设备。')
  // A saved binding never depends on the browser-local companion.
  try {
    return await waitForRemoteWorker(id, 5)
  } catch (cause) {
    const detail = cause instanceof Error ? cause.message : String(cause)
    throw new Error(
      '远程连接失败，消息尚未发送。当前节点绑定的远程执行端未能连接，' +
      '请检查目标设备上的 AgentPark Remote 或 AgentPark 是否已启动、网络是否正常，' +
      '并确认节点的 LinkToRemote 绑定正确后重试。' +
      `\n详细信息：${detail}`,
    )
  }
}
