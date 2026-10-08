import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useScreenShare } from './useScreenShare'

vi.mock('vue', async original => ({ ...await original<typeof import('vue')>(), onBeforeUnmount: vi.fn() }))
let track: { stop: ReturnType<typeof vi.fn>; label: string; applyConstraints: ReturnType<typeof vi.fn>; onended?: () => void; onmute?: () => void }
let selected: MediaStream
let choose: ReturnType<typeof vi.fn>
beforeEach(() => {
  vi.useFakeTimers()
  track = { stop: vi.fn(), label: 'Chosen window', applyConstraints: vi.fn(async () => {}) }
  selected = { getTracks: () => [track], getVideoTracks: () => [track] } as unknown as MediaStream
  choose = vi.fn(async () => selected)
  vi.stubGlobal('navigator', { mediaDevices: { getDisplayMedia: choose } })
  vi.stubGlobal('document', { createElement: (kind: string) => kind === 'video'
    ? { play: async () => {}, pause: vi.fn(), readyState: 2, videoWidth: 1920, videoHeight: 1080 }
    : { getContext: () => ({ drawImage: vi.fn() }), toDataURL: () => 'data:image/jpeg;base64,frame' } })
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

it('shares one picker with RTC and image calls, updates RTC rates and detaches a departing participant', async () => {
  const screen = useScreenShare(), publish = vi.fn(async () => {}), frames = vi.fn(() => true)
  screen.register(1, { kind: 'rtc', name: 'Doubao', stream: publish, fps: () => 12 })
  screen.register(2, { kind: 'frames', name: 'GPT', frame: frames, stop: vi.fn(), limit: () => 64000 })
  await screen.start()
  expect(choose).toHaveBeenCalledOnce(); expect(publish).toHaveBeenLastCalledWith(selected, 5)
  expect(frames).toHaveBeenCalledOnce()
  for (const fps of [1, 30]) {
    await screen.setFrameRate(fps)
    expect(publish).toHaveBeenLastCalledWith(selected, fps)
  }
  expect(screen.rates.value.find(rate => rate.name === 'Doubao')?.fps).toBe(12)
  screen.register(1, null)
  expect(publish).toHaveBeenLastCalledWith(null, 30)
  expect(screen.stream.value).toBe(selected)
  screen.stop()
})

it('queues stop for RTC even when publishing has not resolved yet', async () => {
  let resolve!: () => void
  const publish = vi.fn((stream: MediaStream | null) => stream ? new Promise<void>(r => { resolve = r }) : Promise.resolve())
  const screen = useScreenShare()
  screen.register(1, { kind: 'rtc', name: 'Doubao', stream: publish, fps: () => 0 })
  const start = screen.start()
  await Promise.resolve(); await Promise.resolve()
  screen.stop(); resolve(); await start
  expect(publish).toHaveBeenLastCalledWith(null, 5)
  expect(screen.stream.value).toBeNull()
})

it('sends only to registered vision calls, uses video without system audio, and releases capture on browser stop', async () => {
  const screen = useScreenShare(), receiver = { kind: 'frames' as const, name: 'GPT', frame: vi.fn(() => true), stop: vi.fn(), limit: () => 64000 }
  screen.register(1, receiver)
  await screen.start()
  expect(choose).toHaveBeenCalledWith({ video: { frameRate: { ideal: 5, max: 5 } }, audio: false })
  expect(receiver.frame).toHaveBeenCalledOnce()
  expect(screen.names.value).toBe('GPT')
  track.onended!()
  expect(track.stop).toHaveBeenCalledOnce()
  expect(receiver.stop).toHaveBeenCalledOnce()
  expect(screen.stream.value).toBeNull()
  await vi.advanceTimersByTimeAsync(3000)
  expect(receiver.frame).toHaveBeenCalledOnce()
})

it('releases a picker selection that resolves after hangup', async () => {
  let resolve!: (stream: MediaStream) => void
  choose.mockImplementation(() => new Promise(r => { resolve = r }))
  const screen = useScreenShare(), receiver = { kind: 'frames' as const, name: 'GPT', frame: vi.fn(() => true), stop: vi.fn(), limit: () => 64000 }
  screen.register(1, receiver)
  const opening = screen.start(); screen.stop(); resolve(selected); await opening
  expect(track.stop).toHaveBeenCalledOnce()
  expect(screen.stream.value).toBeNull()
  expect(receiver.frame).not.toHaveBeenCalled()
})

it('reports capture denial without touching the voice call and allows a fresh attempt', async () => {
  choose.mockRejectedValueOnce(new DOMException('denied', 'NotAllowedError'))
  const screen = useScreenShare()
  screen.register(1, { kind: 'frames' as const, name: 'GPT', frame: () => true, stop: vi.fn(), limit: () => 64000 })
  await screen.start()
  expect(screen.error.value).toContain('未开启共享')
  expect(screen.available.value).toBe(true)
  await screen.start(); expect(screen.stream.value).toBe(selected); screen.stop()
})

it('stops capture when the last Realtime participant leaves and discards paused frames', async () => {
  const screen = useScreenShare()
  screen.register(1, { kind: 'frames' as const, name: 'GPT', frame: () => true, stop: vi.fn(), limit: () => 64000 })
  await screen.start(); track.onmute!()
  expect(screen.error.value).toContain('暂停')
  expect(screen.stream.value).toBeNull()
  await screen.start(); screen.register(1, null)
  expect(screen.available.value).toBe(false)
  expect(screen.stream.value).toBeNull()
})

it('keeps capturing at five frames per second and sends fresh frames after backpressure', async () => {
  const screen = useScreenShare(), frame = vi.fn(() => false)
  screen.register(1, { kind: 'frames' as const, name: 'GPT', frame, stop: vi.fn(), limit: () => 64000 })
  await screen.start()
  await vi.advanceTimersByTimeAsync(1000)
  expect(frame).toHaveBeenCalledTimes(6)
  expect(screen.sent.value).toBe(0)
  frame.mockReturnValue(true)
  await vi.advanceTimersByTimeAsync(200)
  expect(frame).toHaveBeenCalledTimes(7)
  expect(screen.sent.value).toBe(1) // No backlog replay.
  screen.stop()
})

it('applies minimum and maximum rates live, rejects out-of-range values and reports actual sends', async () => {
  const screen = useScreenShare(), frame = vi.fn(() => true)
  screen.register(1, { kind: 'frames' as const, name: 'GPT', frame, stop: vi.fn(), limit: () => 64000 })
  await screen.start()
  await screen.setFrameRate(1)
  expect(track.applyConstraints).toHaveBeenLastCalledWith({ frameRate: { ideal: 1, max: 1 } })
  frame.mockClear(); await vi.advanceTimersByTimeAsync(3000)
  expect(frame).toHaveBeenCalledTimes(3)
  expect(screen.rates.value).toEqual([{ id: 1, name: 'GPT', fps: 1 }])
  await screen.setFrameRate(30)
  frame.mockClear(); await vi.advanceTimersByTimeAsync(3000)
  expect(frame).toHaveBeenCalledTimes(90)
  expect(screen.rates.value[0]!.fps).toBeGreaterThanOrEqual(29.5)
  expect(screen.rates.value[0]!.fps).toBeLessThanOrEqual(30.5)
  for (const value of [0, 31, 1.5, NaN, Infinity]) {
    await screen.setFrameRate(value)
    expect(screen.error.value).toContain('1–30')
    expect(screen.frameRate.value).toBe(30)
  }
  expect(track.applyConstraints).toHaveBeenCalledTimes(2)
  frame.mockReturnValue(false); await vi.advanceTimersByTimeAsync(2200)
  expect(screen.rates.value[0]!.fps).toBe(0)
  screen.stop()
})

it('preserves the selected rate on constraint rejection and discards late changes after stop', async () => {
  const screen = useScreenShare()
  screen.register(1, { kind: 'frames' as const, name: 'GPT', frame: () => true, stop: vi.fn(), limit: () => 64000 })
  await screen.start()
  track.applyConstraints.mockRejectedValueOnce(new Error('capture failure'))
  await screen.setFrameRate(30)
  expect(screen.frameRate.value).toBe(5)
  expect(screen.error.value).toContain('capture failure')
  expect(screen.stream.value).toBe(selected)
  let resolve!: () => void
  track.applyConstraints.mockImplementation(() => new Promise<void>(r => { resolve = r }))
  const changing = screen.setFrameRate(1)
  screen.stop(); resolve(); await changing
  expect(screen.frameRate.value).toBe(5)
  expect(screen.stream.value).toBeNull()
  expect(screen.changingRate.value).toBe(false)
})
