import { describe, expect, it } from 'vitest'
import type { MobileNode, NodeInstanceConfig } from '../src/api'
import {
  mergeMobileNodeRuntimeEvent,
  mergeMobileNodeSnapshot,
  mergeNodeConfigSnapshot,
  mergeNodeRuntimeEvent,
} from '../src/nodeRuntimeProjection'

describe('node runtime projection', () => {
  const workingConfig: NodeInstanceConfig = {
    node_id: 'node-1',
    type_id: 'agent_node',
    state: 'working',
    pending_count: 0,
    inflight: { task_id: 'task-1' },
    node_event_seq: 10,
  }

  it('uses explicit terminal tombstones to clear working state', () => {
    const result = mergeNodeRuntimeEvent(workingConfig, {
      state: 'idle',
      pending_count: 0,
      inflight: null,
      _stop_requested: false,
      node_event_seq: 11,
    })

    expect(result.status).toBe('applied')
    expect(result.value).toMatchObject({
      state: 'idle',
      pending_count: 0,
      inflight: null,
      _stop_requested: false,
      node_event_seq: 11,
    })
  })

  it('keeps the newest runtime fields when an older snapshot arrives later', () => {
    const current = {
      ...workingConfig,
      state: 'idle' as const,
      inflight: null,
      node_event_seq: 12,
      name: 'old name',
    }
    const result = mergeNodeConfigSnapshot(current, {
      ...workingConfig,
      node_event_seq: 11,
      name: 'new name',
    })

    expect(result.status).toBe('stale')
    expect(result.value.name).toBe('new name')
    expect(result.value.state).toBe('idle')
    expect(result.value.inflight).toBeNull()
    expect(result.value.node_event_seq).toBe(12)
  })

  it('rejects runtime projections without a sequence contract', () => {
    const result = mergeNodeRuntimeEvent(workingConfig, {
      state: 'idle',
      inflight: null,
    })

    expect(result.status).toBe('invalid')
    expect(result.value).toBe(workingConfig)
  })

  it('maps backend inflight tombstones into mobile summaries', () => {
    const current: MobileNode = {
      id: 'node-1',
      name: 'Node 1',
      type_id: 'agent_node',
      graph_id: 'default',
      state: 'working',
      has_inflight: true,
      stop_requested: true,
      node_event_seq: 20,
    }
    const result = mergeMobileNodeRuntimeEvent(current, {
      state: 'idle',
      pending_count: 0,
      inflight: null,
      _stop_requested: false,
      node_event_seq: 21,
    })

    expect(result.status).toBe('applied')
    expect(result.value).toMatchObject({
      state: 'idle',
      has_inflight: false,
      stop_requested: false,
      node_event_seq: 21,
    })
  })

  it('does not let an older mobile refresh undo a terminal event', () => {
    const current: MobileNode = {
      id: 'node-1',
      name: 'Node 1',
      type_id: 'agent_node',
      graph_id: 'default',
      state: 'idle',
      has_inflight: false,
      node_event_seq: 21,
    }
    const result = mergeMobileNodeSnapshot(current, {
      ...current,
      name: 'Renamed',
      state: 'working',
      has_inflight: true,
      node_event_seq: 20,
    })

    expect(result.status).toBe('stale')
    expect(result.value.name).toBe('Renamed')
    expect(result.value.state).toBe('idle')
    expect(result.value.has_inflight).toBe(false)
    expect(result.value.node_event_seq).toBe(21)
  })
})
