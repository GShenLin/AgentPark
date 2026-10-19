import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { GraphInfo } from '../../api'
import { useGlobalState } from '../../composables/useGlobalState'
import { useNewGraph } from './useNewGraph'

const api = vi.hoisted(() => ({ saveGraph: vi.fn(), listGraphs: vi.fn(), setStartupGraphConfig: vi.fn() }))
vi.mock('../../api', () => api)

const state = useGlobalState()
const original = { id: 'existing', name: 'existing', working_path: 'C:/Project', nodes: [], output_routes: {}, node_notes: { agent: 'Keep me' } }

function setup() {
  const options = {
    graphNameInput: ref('existing'), graphWorkingPathInput: ref('C:/Project'),
    graphs: ref<GraphInfo[]>([{ id: 'existing', name: 'existing' }]), graphStatus: ref<string | null>(null),
  }
  return { ...options, ...useNewGraph(options) }
}

beforeEach(() => {
  vi.resetAllMocks()
  state.currentGraphId.value = 'existing'
  state.currentGraphName.value = 'existing'
  state.currentGraphWorkingPath.value = 'C:/Project'
  state.graphSnapshot.value = original
  state.graphLoadRequest.value = null
  state.selectedNodeId.value = 'agent'
  state.graphNodeFocusRequest.value = { graphId: 'existing', nodeId: 'agent', nonce: 1 }
  state.memoryMode.value = 'graph'
  state.memoryMeta.value = 'existing/agent/memory.md'
  api.saveGraph.mockImplementation(async (id: string) => ({ id, name: id }))
  api.listGraphs.mockResolvedValue([])
  api.setStartupGraphConfig.mockResolvedValue({})
})

describe('NewGraph creation', () => {
  it('saves an independent empty graph and switches through the board load contract', async () => {
    const browser = setup()
    await browser.createNewGraph()
    const id = state.currentGraphId.value!
    expect(id).toMatch(/^graph-[0-9a-f-]{36}$/)
    const empty = { id, name: id, working_path: '', nodes: [], output_routes: {} }
    expect(api.saveGraph).toHaveBeenCalledExactlyOnceWith(id, empty, { saveReason: 'new_empty_graph' })
    expect(state.graphLoadRequest.value).toEqual(empty)
    expect(state.graphSnapshot.value).toEqual(original)
    expect(state.selectedNodeId.value).toBeNull()
    expect(state.graphNodeFocusRequest.value).toBeNull()
    expect(state.memoryMeta.value).toBeNull()
    expect(browser.graphWorkingPathInput.value).toBe('')
    expect(browser.graphNameInput.value).toBe(id)
    expect(api.setStartupGraphConfig).toHaveBeenCalledWith(id, id)
    expect(browser.creating.value).toBe(false)
  })

  it('ignores repeat clicks while creation is pending', async () => {
    let resolveSave!: (graph: GraphInfo) => void
    api.saveGraph.mockImplementation(() => new Promise<GraphInfo>(resolve => { resolveSave = resolve }))
    const browser = setup()
    const first = browser.createNewGraph()
    await browser.createNewGraph()
    expect(api.saveGraph).toHaveBeenCalledTimes(1)
    expect(browser.creating.value).toBe(true)
    resolveSave({ id: api.saveGraph.mock.calls[0]![0], name: 'new' })
    await first
    expect(browser.creating.value).toBe(false)
  })

  it('preserves the current graph and selection when creation fails', async () => {
    api.saveGraph.mockRejectedValue(new Error('Storage unavailable'))
    const browser = setup()
    await browser.createNewGraph()
    expect(state.currentGraphId.value).toBe('existing')
    expect(state.selectedNodeId.value).toBe('agent')
    expect(state.graphLoadRequest.value).toBeNull()
    expect(api.setStartupGraphConfig).not.toHaveBeenCalled()
    expect(browser.graphStatus.value).toBe('Storage unavailable')
    expect(browser.creating.value).toBe(false)
  })

  it('reports startup persistence errors while keeping the created graph accessible', async () => {
    api.setStartupGraphConfig.mockRejectedValue(new Error('Startup save failed'))
    const browser = setup()
    await browser.createNewGraph()
    expect(state.currentGraphId.value).not.toBe('existing')
    expect(browser.graphs.value.map(graph => graph.id)).toContain(state.currentGraphId.value)
    expect(browser.graphStatus.value).toBe('Startup save failed')
  })
})
