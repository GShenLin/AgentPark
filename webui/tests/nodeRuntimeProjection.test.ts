import { describe, expect, it } from 'vitest'
import type { MobileNode, NodeInstanceConfig } from '../src/api'
import {
  mergeMobileNodeRuntimeEvent,
  mergeMobileNodeSnapshot,
  mergeNodeConfigSnapshot,
  mergeNodeEditorConfigSnapshot,
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

  it('preserves diagnostics omitted by an editor config snapshot', () => {
    const current: NodeInstanceConfig = {
      ...workingConfig,
      runtime_events: [{ type: 'runtime_notice', stage: 'provider_request_summary' }],
      runtime_tool_calls: [{ call_id: 'call-1', name: 'workspace_exec' }],
      provider_request_summaries: [{ request_index: 1, approx_input_chars: 3000 }],
      provider_request_totals: { request_count: 1, approx_input_chars: 3000 },
    }
    const result = mergeNodeEditorConfigSnapshot(current, {
      ...workingConfig,
      name: 'Renamed',
      state: 'idle',
      inflight: null,
      node_event_seq: 11,
    })

    expect(result.status).toBe('applied')
    expect(result.value.name).toBe('Renamed')
    expect(result.value.state).toBe('idle')
    expect(result.value.runtime_events).toEqual(current.runtime_events)
    expect(result.value.runtime_tool_calls).toEqual(current.runtime_tool_calls)
    expect(result.value.provider_request_summaries).toEqual(current.provider_request_summaries)
    expect(result.value.provider_request_totals).toEqual(current.provider_request_totals)
  })

  it('projects the latest output resources with the runtime message', () => {
    const result = mergeNodeRuntimeEvent(workingConfig, {
      state: 'idle',
      pending_count: 0,
      inflight: null,
      _stop_requested: false,
      node_event_seq: 11,
      last_message: 'C:/output/matted.png',
      last_output_resources: [{
        type: 'resource',
        resource: { uri: 'C:/output/matted.png', kind: 'image' },
      }],
    })

    expect(result.status).toBe('applied')
    expect(result.value.last_output_resources).toEqual([{
      type: 'resource',
      resource: { uri: 'C:/output/matted.png', kind: 'image' },
    }])
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
