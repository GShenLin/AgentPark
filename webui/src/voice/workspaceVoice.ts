import { inject, ref, shallowReactive, type InjectionKey } from 'vue'
import { createVoiceRoom } from './useVoiceRoom'

export type WorkspaceVoiceSession = {
  id: number
  graphId: string
  nodeId: string
  room: ReturnType<typeof createVoiceRoom>
}

/** One registry per workspace/device. Navigation and layout changes only change views. */
export function createWorkspaceVoice() {
  const sessions = shallowReactive<WorkspaceVoiceSession[]>([])
  const expanded = ref(false)
  let sequence = 0

  function find(graphId: string, nodeId: string) {
    return sessions.find(({ graphId: graph, nodeId: initialNode, room }) => graph === graphId && room.active.value
      && (room.opened.value ? room.participants.value.some(p => p.node === nodeId && p.active) : initialNode === nodeId))
  }
  function status(graphId: string, nodeId: string): 'connecting' | 'connected' | null {
    const session = find(graphId, nodeId)
    if (!session) return null
    return session.room.participants.value.some(p => p.node === nodeId && p.active && p.connected) ? 'connected' : 'connecting'
  }
  function start(graphId: string, nodeId: string) {
    expanded.value = true
    if (find(graphId, nodeId)) return
    const room = createVoiceRoom()
    sessions.push({ id: ++sequence, graphId, nodeId, room })
    // Start capture synchronously within the user's click, required on mobile browsers.
    void room.start(nodeId)
  }
  function hangup(graphId: string, nodeId: string) { find(graphId, nodeId)?.room.leave(nodeId) }
  function dismiss(id: number) {
    const index = sessions.findIndex(session => session.id === id)
    if (index < 0 || sessions[index]!.room.active.value) return
    sessions.splice(index, 1)
  }
  function stopAll() { for (const session of sessions) session.room.stop() }
  return { sessions, expanded, status, start, hangup, dismiss, stopAll }
}

export type WorkspaceVoice = ReturnType<typeof createWorkspaceVoice>
export const workspaceVoiceKey: InjectionKey<WorkspaceVoice> = Symbol('workspaceVoice')
export function useWorkspaceVoice() {
  const workspace = inject(workspaceVoiceKey)
  if (!workspace) throw new Error('Workspace voice context not found')
  return workspace
}
