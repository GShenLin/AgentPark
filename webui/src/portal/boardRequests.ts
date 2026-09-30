let generation = 0
let available = false
let reads = new AbortController()

export class BoardRequestInterruptedError extends Error {
  readonly isRead: boolean
  constructor(isRead: boolean) {
    super(isRead ? '旧连接的读取已取消。' : '连接已中断，操作结果待确认；不会自动重复提交。')
    this.isRead = isRead
  }
}

export function suspendBoardRequests() {
  available = false
  generation += 1
  reads.abort()
  reads = new AbortController()
}

export function resumeBoardRequests() { available = true }

export function captureBoardRequest(init?: RequestInit) {
  if (!available) throw new Error('设备连接已断开，请等待重连。')
  const current = generation
  const isRead = ['GET', 'HEAD'].includes((init?.method || 'GET').toUpperCase())
  return {
    signal: isRead
      ? (init?.signal ? AbortSignal.any([init.signal, reads.signal]) : reads.signal)
      : init?.signal,
    check() {
      if (current !== generation || !available) {
        // Never classify interrupted writes as retryable network errors.
        throw new BoardRequestInterruptedError(isRead)
      }
    },
  }
}
