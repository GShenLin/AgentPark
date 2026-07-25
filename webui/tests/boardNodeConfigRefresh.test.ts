import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref, type Ref } from 'vue'
import type { NodeInstanceConfig, NodeInstanceConfigListResponse, NodeInstanceState } from '../src/api'
import type { NodeCard, NodeRunState } from '../src/components/agent-board/context'

const apiMocks = vi.hoisted(() => ({
  getNodeInstanceConfig: vi.fn(),
  listNodeInstanceConfigs: vi.fn(),
}))

vi.mock('../src/api', () => apiMocks)

import { createBoardNodeConfigRefresh } from '../src/components/agent-board/boardNodeConfigRefresh'

type Deferred<T> = {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve
  })
  return { promise, resolve }
}

function nodeConfig(graphId: string, nodeId: string): NodeInstanceConfig {
  return {
    graph_id: graphId,
    node_id: nodeId,
    type_id: 'agent_node',
    name: nodeId,
    state: 'idle',
    node_event_seq: 0,
    ui: { x: 10, y: 20 },
  }
}

function configList(graphId: string, nodeId: string, version: number): NodeInstanceConfigListResponse {
  return {
    nodes: [nodeConfig(graphId, nodeId)],
    node_ids: [nodeId],
    partial: false,
    version,
  }
}

function createSubject(currentGraphId: Ref<string | null>) {
  const nodes = ref<NodeCard[]>([])
  const nodeConfigs = ref<Record<string, NodeInstanceConfig>>({})
  const nodeStates = ref<Record<string, NodeInstanceState>>({})
  const subject = createBoardNodeConfigRefresh({
    currentGraphId,
    selectedNodeId: ref<string | null>(null),
    nodes,
    nodeConfigs,
    nodeStates,
    nodeRuns: ref<Record<string, NodeRunState>>({}),
    activeDragItemIds: new Set<string>(),
    pendingUiPositions: new Map(),
    getItemPosition: () => null,
    clearPendingUiPosition: vi.fn(),
    triggerNodeDone: vi.fn(),
    syncSelectedNodeWorkingPath: vi.fn(),
    requestMemoryRefresh: vi.fn(),
  })
  return { nodeConfigs, nodeStates, nodes, subject }
}

describe('board node config refresh isolation', () => {
  beforeEach(() => {
    apiMocks.getNodeInstanceConfig.mockReset()
    apiMocks.listNodeInstanceConfigs.mockReset()
  })

  it('starts the new graph refresh and discards the previous graph response', async () => {
    const defaultResponse = deferred<NodeInstanceConfigListResponse>()
    const xyjResponse = deferred<NodeInstanceConfigListResponse>()
    apiMocks.listNodeInstanceConfigs.mockImplementation((graphId: string) => {
      if (graphId === 'default') return defaultResponse.promise
      if (graphId === 'XYJ') return xyjResponse.promise
      throw new Error(`unexpected graph ${graphId}`)
    })

    const currentGraphId = ref<string | null>('default')
    const { nodes, subject } = createSubject(currentGraphId)
    const defaultRefresh = subject.refreshNodeConfigs()

    currentGraphId.value = 'XYJ'
    nodes.value = []
    subject.resetNodeConfigWatermark()
    const xyjRefresh = subject.refreshNodeConfigs()

    expect(apiMocks.listNodeInstanceConfigs.mock.calls).toEqual([
      ['default', 0, 'board'],
      ['XYJ', 0, 'board'],
    ])

    defaultResponse.resolve(configList('default', 'default-crash-node', 100))
    await defaultRefresh
    expect(nodes.value).toEqual([])

    xyjResponse.resolve(configList('XYJ', 'xyj-node', 200))
    await xyjRefresh
    expect(nodes.value.map((node) => node.id)).toEqual(['xyj-node'])
  })

  it('discards an older request when the same graph is reloaded', async () => {
    const oldResponse = deferred<NodeInstanceConfigListResponse>()
    const newResponse = deferred<NodeInstanceConfigListResponse>()
    apiMocks.listNodeInstanceConfigs
      .mockImplementationOnce(() => oldResponse.promise)
      .mockImplementationOnce(() => newResponse.promise)

    const currentGraphId = ref<string | null>('XYJ')
    const { nodes, subject } = createSubject(currentGraphId)
    const oldRefresh = subject.refreshNodeConfigs()

    nodes.value = []
    subject.resetNodeConfigWatermark()
    const newRefresh = subject.refreshNodeConfigs()

    oldResponse.resolve(configList('XYJ', 'stale-node', 100))
    await oldRefresh
    expect(nodes.value).toEqual([])

    newResponse.resolve(configList('XYJ', 'current-node', 200))
    await newRefresh
    expect(nodes.value.map((node) => node.id)).toEqual(['current-node'])
  })

  it('clears inflight on the terminal runtime event and rejects an older event', async () => {
    const working = {
      ...nodeConfig('default', 'crash-node'),
      state: 'working' as const,
      node_event_seq: 340,
      inflight: { task_id: 'task-1' },
    }
    apiMocks.listNodeInstanceConfigs.mockResolvedValue({
      nodes: [working],
      node_ids: ['crash-node'],
      partial: false,
      version: 1,
    })

    const currentGraphId = ref<string | null>('default')
    const { nodeConfigs, nodeStates, subject } = createSubject(currentGraphId)
    await subject.refreshNodeConfigs()

    subject.applyNodeRuntimeEvent({
      event: 'executor_task_finished',
      node_id: 'crash-node',
      node_runtime: {
        node_id: 'crash-node',
        state: 'idle',
        pending_count: 0,
        inflight: null,
        _stop_requested: false,
        node_event_seq: 341,
      },
    })

    expect(nodeStates.value['crash-node']).toBe('idle')
    expect(nodeConfigs.value['crash-node']?.inflight).toBeNull()
    expect(subject.hasActiveNodeWork()).toBe(false)

    subject.applyNodeRuntimeEvent({
      event: 'node_message_done',
      node_id: 'crash-node',
      node_runtime: {
        node_id: 'crash-node',
        state: 'working',
        pending_count: 0,
        inflight: { task_id: 'task-1' },
        _stop_requested: false,
        node_event_seq: 340,
      },
    })

    expect(nodeStates.value['crash-node']).toBe('idle')
    expect(nodeConfigs.value['crash-node']?.node_event_seq).toBe(341)
    expect(subject.hasActiveNodeWork()).toBe(false)
  })
})
