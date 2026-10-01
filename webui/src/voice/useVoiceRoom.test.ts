import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useVoiceRoom } from './useVoiceRoom'
import { ConferenceAudio } from './ConferenceAudio'

vi.mock('vue', async original => ({ ...await original<typeof import('vue')>(), onBeforeUnmount: vi.fn() }))
vi.mock('./ConferenceAudio', () => ({ ConferenceAudio: vi.fn(class {
  open = vi.fn(async () => {})
  close = vi.fn(async () => {})
  muteMicrophone = vi.fn()
}) }))
beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('AudioContext', class {})
  vi.stubGlobal('RTCPeerConnection', class {})
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn() } })
})
afterEach(() => vi.unstubAllGlobals())

it('adds nodes to the ongoing single-node call without restarting it or acquiring another microphone', async () => {
  const room = useVoiceRoom()
  await room.start('GPT')
  const original = room.participants.value[0]!, mixer = room.audio.value!
  room.stateChanged(original.id, true, true)
  room.add(['Agent', 'PCG', 'Agent', 'GPT'])
  expect(room.participants.value.map(p => p.node)).toEqual(['GPT', 'Agent', 'PCG'])
  expect(room.participants.value[0]).toBe(original)
  expect(original.connected).toBe(true)
  expect(room.audio.value).toBe(mixer)
  expect(ConferenceAudio).toHaveBeenCalledOnce()
  expect(mixer.open).toHaveBeenCalledOnce()
  expect(mixer.close).not.toHaveBeenCalled()
  room.stop()
})

it('keeps the original node connected if an added node fails; rejoining ignores stale events', async () => {
  const room = useVoiceRoom(); await room.start('GPT'); room.add(['Agent'])
  const main = room.participants.value[0]!, old = room.participants.value[1]!
  room.stateChanged(main.id, true, true)
  room.stateChanged(old.id, false, false)
  expect(room.active.value).toBe(true)
  room.add(['Agent']); const replacement = room.participants.value[1]!
  expect(replacement.id).not.toBe(old.id)
  room.stateChanged(old.id, false, false)
  expect(replacement.active).toBe(true)
  expect(main.connected).toBe(true)
  room.stateChanged(main.id, false, false)
  expect(room.active.value).toBe(true)
  room.stateChanged(replacement.id, false, false)
  expect(room.active.value).toBe(false)
  expect(room.audio.value!.close).toHaveBeenCalledOnce()
})

it('does not create participants after hanging up while microphone permission is pending', async () => {
  let release!: () => void
  vi.mocked(ConferenceAudio).mockImplementationOnce(class {
    open = vi.fn(() => new Promise<void>(resolve => { release = resolve }))
    close = vi.fn(async () => {})
    muteMicrophone = vi.fn()
  } as unknown as typeof ConferenceAudio)
  const room = useVoiceRoom(), opening = room.start('GPT')
  room.stop(); release(); await opening
  expect(room.active.value).toBe(false)
  expect(room.participants.value).toEqual([])
  expect(room.audio.value!.close).toHaveBeenCalledOnce()
})
