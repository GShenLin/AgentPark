import { afterEach, expect, it, vi } from 'vitest'
import { waitForRestart } from '../src/utils/serverRestart'

afterEach(() => vi.useRealTimers())

it('waits through the old process and downtime until a new instance responds', async () => {
  vi.useFakeTimers()
  const read = vi.fn()
    .mockResolvedValueOnce({ ok: true, instance_id: 'old' })
    .mockRejectedValueOnce(new Error('connection refused'))
    .mockResolvedValueOnce({ ok: true, instance_id: 'new' })
  const completed = vi.fn()
  const pending = waitForRestart('old', read).then(completed)
  await vi.advanceTimersByTimeAsync(2_000)
  expect(completed).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(1_000)
  await pending
  expect(completed).toHaveBeenCalledOnce()
})

it('reports timeout rather than treating the original process as a successful restart', async () => {
  vi.useFakeTimers()
  const pending = waitForRestart('old', async () => ({ ok: true, instance_id: 'old' }), 2_000)
  const assertion = expect(pending).rejects.toThrow('Restart timed out')
  await vi.advanceTimersByTimeAsync(2_000)
  await assertion
})

it('aborts a stalled status request and reports timeout', async () => {
  vi.useFakeTimers()
  const pending = waitForRestart('old', signal => new Promise((_, reject) => {
    signal.addEventListener('abort', () => reject(new Error('aborted')))
  }), 2_000)
  const assertion = expect(pending).rejects.toThrow('Restart timed out')
  await vi.advanceTimersByTimeAsync(2_000)
  await assertion
})
