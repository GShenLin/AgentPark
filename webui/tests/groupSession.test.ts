import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref, type EffectScope } from 'vue'
import { useBoardGroups } from '../src/groups/useBoardGroups'
import type { AgentGroup } from '../src/groups/groupApi'
import type { NodeCard } from '../src/components/agent-board/context'

const api = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), move: vi.fn(), dissolve: vi.fn() }))
vi.mock('../src/groups/groupApi', () => ({ groupApi: api }))
vi.mock('../src/composables/useAppEventStream', () => ({ subscribeAppEvents: () => () => {} }))
vi.mock('vue', async importOriginal => ({
  ...await importOriginal<typeof import('vue')>(), onMounted: () => {}, onBeforeUnmount: () => {},
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
const group: AgentGroup = {
  id: 'team', name: 'Team', objective: '', bounds: { x: 0, y: 0, width: 600, height: 500 },
  members: [], tasks: [], revision: 1, private: false, dissolved: false, created_at: '', updated_at: '',
}
const scopes: EffectScope[] = []
async function setup() {
  const graphId = ref<string | null>('first')
  const ready = ref(true)
  const nodes = ref<NodeCard[]>(['a', 'b'].map(id => ({
    id, name: id, typeId: 'agent_node', inputNum: 1, outputNum: 1,
    ui: { grid_x: 0, grid_y: 0, width: 230, height: 250 }, last_message: null,
  })))
  const scope = effectScope(); scopes.push(scope)
  const state = scope.run(() => useBoardGroups({ graphId, ready, nodes, selectedIds: ref(['a', 'b']),
    grid: ref({ cellWidth: 300, cellHeight: 320 }), lastError: ref(null), board: ref(null) }))!
  await nextTick()
  return { state, graphId, ready }
}
beforeEach(() => {
  vi.resetAllMocks()
  api.list.mockResolvedValue({ groups: [] })
  api.move.mockResolvedValue({ group })
})
afterEach(() => { for (const scope of scopes.splice(0)) scope.stop() })

describe('group commands across graph and connection changes', () => {
  it('does not create a group after its prerequisite read belongs to the previous graph', async () => {
    const { state, graphId } = await setup()
    const read = deferred<{ groups: AgentGroup[] }>()
    api.list.mockReturnValueOnce(read.promise)
    const command = state.toggleSelection()
    await nextTick()
    graphId.value = 'second'
    await nextTick()
    read.resolve({ groups: [] })
    await command
    expect(api.create).not.toHaveBeenCalled()
    expect(state.busy.value).toBe(false)
  })

  it('does not replay a pending membership change after reconnect', async () => {
    const { state, ready } = await setup()
    const read = deferred<{ groups: AgentGroup[] }>()
    api.list.mockReturnValueOnce(read.promise)
    const command = state.afterNodeDrop(['a'])
    await nextTick()
    ready.value = false; await nextTick()
    ready.value = true; await nextTick()
    read.resolve({ groups: [group] })
    await command
    expect(api.move).not.toHaveBeenCalled()
  })

  it('stops the remaining batch when navigation occurs during an already submitted move', async () => {
    const { state, graphId } = await setup()
    api.list.mockResolvedValue({ groups: [group] })
    const moved = deferred<{ group: AgentGroup }>()
    api.move.mockReturnValueOnce(moved.promise)
    const command = state.afterNodeDrop(['a', 'b'])
    await vi.waitFor(() => expect(api.move).toHaveBeenCalledTimes(1))
    graphId.value = 'second'; await nextTick()
    moved.resolve({ group })
    await command
    expect(api.move).toHaveBeenCalledTimes(1)
    expect(api.move.mock.calls[0]?.slice(0, 2)).toEqual(['first', 'a'])
  })
})
