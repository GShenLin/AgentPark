import { ApiHttpError, ApiNetworkError } from '../api'
import { BoardRequestInterruptedError, BoardUnavailableError } from '../portal/boardRequests'

export function voiceRetryable(error: unknown) {
  return error instanceof ApiNetworkError || error instanceof BoardRequestInterruptedError || error instanceof BoardUnavailableError
    || (error instanceof ApiHttpError && [408, 429, 502, 503, 504].includes(error.status))
}

export function voiceDelay(signal: AbortSignal, milliseconds: number) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) { reject(signal.reason); return }
    const aborted = () => { clearTimeout(timer); reject(signal.reason) }
    const timer = setTimeout(() => { signal.removeEventListener('abort', aborted); resolve() }, milliseconds)
    signal.addEventListener('abort', aborted, { once: true })
  })
}

/** Only use for reads or server-enforced idempotent writes with the same payload. */
export async function voiceRetry<T>(work: () => Promise<T>, signal: AbortSignal, status: (message: string) => void): Promise<T> {
  let attempts = 0
  while (!signal.aborted) {
    try { return await work() }
    catch (error) {
      if (signal.aborted || !voiceRetryable(error)) throw error
      status(`连接中断，正在恢复消息同步：${error instanceof Error ? error.message : String(error)}`)
      await voiceDelay(signal, Math.min(500 * 2 ** Math.min(attempts++, 4), 8000))
    }
  }
  throw signal.reason
}
