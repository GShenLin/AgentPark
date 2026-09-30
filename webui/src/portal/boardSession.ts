import { readonly, ref, type InjectionKey } from 'vue'

export interface BoardSessionParticipant {
  suspend(): void
  restore(): Promise<void>
  activate?(): void
}

/** A transport replacement refreshes participants without recreating their UI. */
export function createBoardSession() {
  const phase = ref<'offline' | 'restoring' | 'ready'>('offline')
  const participants = new Set<BoardSessionParticipant>()
  let generation = 0
  function suspend() {
    generation += 1
    phase.value = 'offline'
    for (const participant of participants) participant.suspend()
  }
  async function restore() {
    const current = ++generation
    phase.value = 'restoring'
    try {
      // Parent access checks run before child data refreshes.
      for (const participant of participants) {
        await participant.restore()
        if (current !== generation) throw new Error('连接已变化，请重新连接。')
      }
      for (const participant of participants) participant.activate?.()
      phase.value = 'ready'
    } catch (cause) {
      if (current === generation) suspend()
      throw cause
    }
  }
  function register(participant: BoardSessionParticipant) {
    participants.add(participant)
    return () => participants.delete(participant)
  }
  return { phase: readonly(phase), suspend, restore, register }
}

export const cloudBoardSession: InjectionKey<ReturnType<typeof createBoardSession>> = Symbol('cloud-board-session')
