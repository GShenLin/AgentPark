import { onBeforeUnmount, onMounted, readonly, ref, type Ref } from 'vue'

const sharedNowMs = ref(Date.now())

let activeConsumers = 0
let sharedTimer: ReturnType<typeof setInterval> | null = null

function updateSharedNow() {
  sharedNowMs.value = Date.now()
}

function startSharedTicker() {
  activeConsumers += 1
  updateSharedNow()
  if (sharedTimer !== null) return
  sharedTimer = setInterval(updateSharedNow, 1000)
  document.addEventListener('visibilitychange', updateSharedNow)
}

function stopSharedTicker() {
  activeConsumers = Math.max(0, activeConsumers - 1)
  if (activeConsumers > 0 || sharedTimer === null) return
  clearInterval(sharedTimer)
  sharedTimer = null
  document.removeEventListener('visibilitychange', updateSharedNow)
}

export function useSharedBoardClockNow(): Readonly<Ref<number>> {
  onMounted(startSharedTicker)
  onBeforeUnmount(stopSharedTicker)
  return readonly(sharedNowMs)
}

export function boardClockRemainingSeconds(nextFireAt: unknown, nowMs: number): number | null {
  const nextFireAtSeconds = typeof nextFireAt === 'number'
    ? nextFireAt
    : typeof nextFireAt === 'string' && nextFireAt.trim()
      ? Number(nextFireAt.trim())
      : Number.NaN
  if (!Number.isFinite(nextFireAtSeconds)) return null
  return Math.max(0, Math.ceil((nextFireAtSeconds * 1000 - nowMs) / 1000))
}

export function formatBoardClockCountdown(
  nextFireAt: unknown,
  nowMs: number,
  fallback = '',
): string {
  const remainingSeconds = boardClockRemainingSeconds(nextFireAt, nowMs)
  return remainingSeconds === null ? fallback : `Working: ${remainingSeconds}s`
}
