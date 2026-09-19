import type { InjectionKey } from 'vue'

export const cloudBoardRestart: InjectionKey<() => Promise<{ ok: boolean }>> = Symbol('cloud-board-restart')
