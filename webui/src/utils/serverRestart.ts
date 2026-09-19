export interface ServerStatus {
  ok: boolean
  instance_id: string
}

export async function waitForRestart(
  previousInstance: string,
  readStatus: (signal: AbortSignal) => Promise<ServerStatus>,
  timeoutMs = 300_000,
  options: { signal?: AbortSignal; pollTimeoutMs?: number } = {},
) {
  if (!previousInstance) throw new Error('Restart response is missing the server instance ID.')
  const deadline = Date.now() + timeoutMs
  let lastError = 'The original server is still running.'
  while (Date.now() < deadline) {
    options.signal?.throwIfAborted()
    await new Promise(resolve => setTimeout(resolve, 1_000))
    options.signal?.throwIfAborted()
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), Math.max(1, Math.min(options.pollTimeoutMs ?? 5_000, deadline - Date.now())))
    try {
      const status = await readStatus(controller.signal)
      if (!status.ok || !status.instance_id) throw new Error('Invalid server status response.')
      if (status.instance_id !== previousInstance) return
      lastError = 'The original server is still running.'
    } catch (error) {
      lastError = String(error instanceof Error ? error.message : error)
    } finally {
      clearTimeout(timer)
    }
  }
  throw new Error(`Restart timed out. Check .runtime/restart.log on the server. ${lastError}`)
}
