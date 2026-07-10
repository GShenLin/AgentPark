import type {
  RuntimeEventAction,
  RuntimeEventConfig,
  RuntimeEventName,
  RuntimeEventReceiverGroup,
  RuntimeEventRule,
  RuntimeEventRules,
} from './api'

export const RUNTIME_EVENT_NAMES: RuntimeEventName[] = [
  'OnInput',
  'ToolFailure',
  'RuntimeNotice',
  'NetError',
  'WorkPersisted',
  'WorkFailed',
]

export const RUNTIME_EVENT_ACTIONS: RuntimeEventAction[] = [
  'context.produce',
  'notice.write',
  'node.dispatch',
]

export const RUNTIME_EVENT_TTLS = ['current_run', 'next_turn', 'persistent']
export const RUNTIME_EVENT_PRIORITIES = ['low', 'normal', 'high']

export function cloneRuntimeEventConfig(config: RuntimeEventConfig | Record<string, unknown>): RuntimeEventConfig {
  const cloned = JSON.parse(JSON.stringify(config || {})) as Partial<RuntimeEventConfig>
  return {
    schema_version: Number(cloned.schema_version || 1),
    enabled: cloned.enabled !== false,
    rules: normalizeRules(cloned.rules),
    context_producers: objectMap(cloned.context_producers),
    notice_writers: objectMap(cloned.notice_writers),
    receiver_groups: objectMap(cloned.receiver_groups) as Record<string, RuntimeEventReceiverGroup>,
    context_policy: objectMap(cloned.context_policy),
  }
}

export function rulesForNode(config: RuntimeEventConfig, graphId: string, nodeId: string) {
  return flattenRules(config.rules || {})
    .filter((item) => item.graphId === graphId && item.nodeId === nodeId)
}

export function targetOptionsForAction(config: RuntimeEventConfig, action: string) {
  if (action === 'context.produce') return Object.keys(config.context_producers || {})
  if (action === 'notice.write') return Object.keys(config.notice_writers || {})
  if (action === 'node.dispatch') return Object.keys(config.receiver_groups || {})
  return []
}

export function defaultTargetForAction(config: RuntimeEventConfig, action: string) {
  const options = targetOptionsForAction(config, action)
  if (options.length) return options[0] || ''
  if (action === 'node.dispatch') return 'companion'
  return ''
}

export function ensureCompanionReceiverGroup(
  config: RuntimeEventConfig,
  groupId: string,
  event: string,
  profileId: string,
) {
  if (!groupId || groupId in config.receiver_groups) {
    const existing = config.receiver_groups[groupId]
    if (existing && event && profileId) {
      existing.event_profiles = { ...(existing.event_profiles || {}), [event]: profileId }
    }
    return
  }
  config.receiver_groups[groupId] = {
    enabled: true,
    graph_id: 'Companion',
    merge_target: {
      graph_id: 'Companion',
      node_id: 'Companion',
    },
    event_profiles: event && profileId ? { [event]: profileId } : {},
    receivers: [],
  }
}

export function makeRuntimeEventRule(payload: {
  event: string
  action: string
  target: string
  params?: RuntimeEventRule['params']
}): RuntimeEventRule {
  const params = payload.params || {}
  return {
    enabled: true,
    action: payload.action,
    target: payload.target,
    params: Object.keys(params).length ? params : {},
  }
}

export function setRuntimeEventRule(
  config: RuntimeEventConfig,
  payload: {
    graphId: string
    nodeId: string
    event: string
    rule: RuntimeEventRule
  },
) {
  if (!config.rules) config.rules = {}
  const eventRules = config.rules[payload.event] || {}
  const graphRules = eventRules[payload.graphId] || {}
  const existing = normalizeRuleList(graphRules[payload.nodeId])
  graphRules[payload.nodeId] = [...existing, payload.rule]
  eventRules[payload.graphId] = graphRules
  config.rules[payload.event] = eventRules
}

export function deleteRuntimeEventRule(
  config: RuntimeEventConfig,
  payload: {
    graphId: string
    nodeId: string
    event: string
    ruleIndex?: number
  },
) {
  const eventRules = config.rules?.[payload.event]
  const graphRules = eventRules?.[payload.graphId]
  if (!graphRules) return
  if (typeof payload.ruleIndex === 'number') {
    const nextRules = normalizeRuleList(graphRules[payload.nodeId]).filter((_rule, index) => index !== payload.ruleIndex)
    if (nextRules.length) graphRules[payload.nodeId] = nextRules
    else delete graphRules[payload.nodeId]
  } else {
    delete graphRules[payload.nodeId]
  }
  if (!Object.keys(graphRules).length) delete eventRules[payload.graphId]
  if (eventRules && !Object.keys(eventRules).length) delete config.rules[payload.event]
}

export function flattenRules(rules: RuntimeEventRules) {
  const output: Array<{
    event: string
    graphId: string
    nodeId: string
    rule: RuntimeEventRule
    ruleIndex: number
  }> = []
  for (const [event, eventRules] of Object.entries(rules || {})) {
    if (!eventRules || typeof eventRules !== 'object' || Array.isArray(eventRules)) continue
    for (const [graphId, graphRules] of Object.entries(eventRules)) {
      if (!graphRules || typeof graphRules !== 'object' || Array.isArray(graphRules)) continue
      for (const [nodeId, nodeRules] of Object.entries(graphRules)) {
        normalizeRuleList(nodeRules).forEach((rule, ruleIndex) => {
          output.push({ event, graphId, nodeId, rule, ruleIndex })
        })
      }
    }
  }
  return output
}

export function formatRuntimeApplyErrors(errors: unknown) {
  if (!Array.isArray(errors) || errors.length === 0) return 'Runtime event config validation failed.'
  return errors
    .slice(0, 6)
    .map((item) => {
      if (!item || typeof item !== 'object') return String(item)
      const obj = item as Record<string, unknown>
      const where = String(obj.config_path || obj.field || '').trim()
      const message = String(obj.message || '').trim()
      return where ? `${where}: ${message}` : message
    })
    .filter(Boolean)
    .join('; ')
}

function objectMap(value: unknown): Record<string, any> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
}

function normalizeRules(value: unknown): RuntimeEventRules {
  if (Array.isArray(value)) {
    const output: RuntimeEventRules = {}
    for (const item of value) {
      if (!item || typeof item !== 'object' || Array.isArray(item)) continue
      const raw = item as Record<string, any>
      const event = String(raw.event || '').trim()
      const graphId = String(raw.source?.graph_id || '').trim()
      const nodeId = String(raw.source?.node_id || '').trim()
      if (!event || !graphId || !nodeId) continue
      const { source: _source, event: _event, ...rule } = raw
      if (!output[event]) output[event] = {}
      if (!output[event][graphId]) output[event][graphId] = {}
      const existing = normalizeRuleList(output[event][graphId][nodeId])
      output[event][graphId][nodeId] = [...existing, rule as RuntimeEventRule]
    }
    return output
  }
  const rawRules = objectMap(value)
  const output: RuntimeEventRules = {}
  for (const [event, eventRules] of Object.entries(rawRules)) {
    if (!eventRules || typeof eventRules !== 'object' || Array.isArray(eventRules)) continue
    for (const [graphId, graphRules] of Object.entries(eventRules as Record<string, unknown>)) {
      if (!graphRules || typeof graphRules !== 'object' || Array.isArray(graphRules)) continue
      for (const [nodeId, nodeRules] of Object.entries(graphRules as Record<string, unknown>)) {
        const normalized = normalizeRuleList(nodeRules)
        if (!normalized.length) continue
        if (!output[event]) output[event] = {}
        if (!output[event][graphId]) output[event][graphId] = {}
        output[event][graphId][nodeId] = normalized
      }
    }
  }
  return output
}

function normalizeRuleList(value: unknown): RuntimeEventRule[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is RuntimeEventRule => !!item && typeof item === 'object' && !Array.isArray(item))
  }
  if (value && typeof value === 'object') return [value as RuntimeEventRule]
  return []
}
