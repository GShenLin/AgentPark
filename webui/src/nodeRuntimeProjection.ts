import type { MobileNode, NodeInstanceConfig, NodeInstanceState } from './apiTypes'

const NODE_RUNTIME_FIELDS = [
  'state',
  'pending',
  'pending_count',
  'held_outputs',
  'inflight',
  'inflight_at',
  '_stop_requested',
  '_delete_requested',
  'node_event_seq',
  'last_message',
  'last_run_at',
  'last_runtime_event',
  'runtime_events',
  'runtime_tool_calls',
  'provider_request_summaries',
  'provider_request_totals',
  'completed_requests',
  'last_completed_request',
  'goal',
  'goal_state',
  '_clock_running',
  '_clock_next_fire_at',
  '_clock_remaining_seconds',
  '_clock_trigger_count',
] as const

const MOBILE_RUNTIME_FIELDS = [
  'state',
  'pending_count',
  'node_event_seq',
  'has_inflight',
  'stop_requested',
  'last_message',
  'last_run_at',
  'last_runtime_event',
  'runtime_tool_calls',
  'goal',
  'goal_state',
] as const

type RuntimeRecord = Record<string, unknown>
type MergeStatus = 'applied' | 'stale' | 'invalid'

export type RuntimeProjectionMerge<T> = {
  status: MergeStatus
  value: T
  error?: string
}

function isRecord(value: unknown): value is RuntimeRecord {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function hasOwn(value: RuntimeRecord, field: string) {
  return Object.prototype.hasOwnProperty.call(value, field)
}

function readSequence(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null
}

function projectionError(projection: RuntimeRecord): string | null {
  if (readSequence(projection.node_event_seq) === null) {
    return 'node runtime projection requires a non-negative integer node_event_seq'
  }
  if (hasOwn(projection, 'state') && !['idle', 'working', 'stop'].includes(String(projection.state))) {
    return 'node runtime projection state must be idle, working, or stop'
  }
  if (
    hasOwn(projection, 'pending_count')
    && (readSequence(projection.pending_count) === null)
  ) {
    return 'node runtime projection pending_count must be a non-negative integer'
  }
  if (
    hasOwn(projection, 'inflight')
    && projection.inflight !== null
    && !isRecord(projection.inflight)
  ) {
    return 'node runtime projection inflight must be an object or null'
  }
  if (hasOwn(projection, '_stop_requested') && typeof projection._stop_requested !== 'boolean') {
    return 'node runtime projection _stop_requested must be a boolean'
  }
  return null
}

function currentSequence(value: RuntimeRecord) {
  return readSequence(value.node_event_seq) ?? -1
}

function mergePersistentConfig(
  current: NodeInstanceConfig | undefined,
  incoming: NodeInstanceConfig,
): NodeInstanceConfig {
  const persistent = { ...incoming } as RuntimeRecord
  for (const field of NODE_RUNTIME_FIELDS) delete persistent[field]
  return { ...(current || {}), ...persistent } as NodeInstanceConfig
}

export function mergeNodeConfigSnapshot(
  current: NodeInstanceConfig | undefined,
  incoming: NodeInstanceConfig,
): RuntimeProjectionMerge<NodeInstanceConfig> {
  const projection = incoming as RuntimeRecord
  const base = mergePersistentConfig(current, incoming)
  const error = projectionError(projection)
  if (error) return { status: 'invalid', value: current ? base : incoming, error }
  if (current && Number(projection.node_event_seq) < currentSequence(current as RuntimeRecord)) {
    return { status: 'stale', value: base }
  }

  const next = { ...base } as RuntimeRecord
  for (const field of NODE_RUNTIME_FIELDS) delete next[field]
  for (const field of NODE_RUNTIME_FIELDS) {
    if (hasOwn(projection, field)) next[field] = projection[field]
  }
  return { status: 'applied', value: next as NodeInstanceConfig }
}

export function mergeNodeRuntimeEvent(
  current: NodeInstanceConfig,
  incoming: unknown,
): RuntimeProjectionMerge<NodeInstanceConfig> {
  if (!isRecord(incoming)) {
    return { status: 'invalid', value: current, error: 'node runtime projection must be an object' }
  }
  const error = projectionError(incoming)
  if (error) return { status: 'invalid', value: current, error }
  if (Number(incoming.node_event_seq) < currentSequence(current as RuntimeRecord)) {
    return { status: 'stale', value: current }
  }

  const next = { ...current } as RuntimeRecord
  for (const field of NODE_RUNTIME_FIELDS) {
    if (hasOwn(incoming, field)) next[field] = incoming[field]
  }
  return { status: 'applied', value: next as NodeInstanceConfig }
}

function mergePersistentMobileNode(current: MobileNode | undefined, incoming: MobileNode): MobileNode {
  const persistent = { ...incoming } as RuntimeRecord
  for (const field of MOBILE_RUNTIME_FIELDS) delete persistent[field]
  return { ...(current || {}), ...persistent } as MobileNode
}

export function mergeMobileNodeSnapshot(
  current: MobileNode | undefined,
  incoming: MobileNode,
): RuntimeProjectionMerge<MobileNode> {
  const incomingSequence = readSequence(incoming.node_event_seq)
  const base = mergePersistentMobileNode(current, incoming)
  if (incomingSequence === null) {
    return {
      status: 'invalid',
      value: current ? base : incoming,
      error: 'mobile node snapshot requires a non-negative integer node_event_seq',
    }
  }
  if (current && incomingSequence < currentSequence(current as RuntimeRecord)) {
    return { status: 'stale', value: base }
  }

  const next = { ...base } as RuntimeRecord
  for (const field of MOBILE_RUNTIME_FIELDS) delete next[field]
  for (const field of MOBILE_RUNTIME_FIELDS) {
    if (hasOwn(incoming as RuntimeRecord, field)) next[field] = incoming[field]
  }
  return { status: 'applied', value: next as MobileNode }
}

export function mergeMobileNodeRuntimeEvent(
  current: MobileNode,
  incoming: unknown,
): RuntimeProjectionMerge<MobileNode> {
  if (!isRecord(incoming)) {
    return { status: 'invalid', value: current, error: 'node runtime projection must be an object' }
  }
  const error = projectionError(incoming)
  if (error) return { status: 'invalid', value: current, error }
  if (Number(incoming.node_event_seq) < currentSequence(current as RuntimeRecord)) {
    return { status: 'stale', value: current }
  }

  const next: MobileNode = { ...current, node_event_seq: Number(incoming.node_event_seq) }
  if (hasOwn(incoming, 'state')) next.state = incoming.state as NodeInstanceState
  if (hasOwn(incoming, 'pending_count')) next.pending_count = Number(incoming.pending_count)
  if (hasOwn(incoming, 'inflight')) next.has_inflight = isRecord(incoming.inflight)
  if (hasOwn(incoming, '_stop_requested')) next.stop_requested = incoming._stop_requested as boolean
  if (hasOwn(incoming, 'last_run_at')) next.last_run_at = String(incoming.last_run_at || '')
  if (hasOwn(incoming, 'goal')) next.goal = String(incoming.goal || '')
  if (hasOwn(incoming, 'goal_state')) {
    next.goal_state = isRecord(incoming.goal_state) ? incoming.goal_state : null
  }
  return { status: 'applied', value: next }
}
