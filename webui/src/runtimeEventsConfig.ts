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
  'context.append_file',
  'notice.write',
  'node.dispatch',
]

export const RUNTIME_EVENT_ACTION_LABELS: Record<string, string> = {
  'context.produce': '生成上下文',
  'context.append_file': 'AppendFile',
  'notice.write': '弹窗通知',
  'node.dispatch': '交给 Agent 处理',
}

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

export function eventNodesForNode(config: RuntimeEventConfig, graphId: string, nodeId: string) {
  const output: Array<{ event: string; graphId: string; nodeId: string; handlers: RuntimeEventRule[] }> = []
  for (const [event, eventRules] of Object.entries(config.rules || {})) {
    const handlers = eventRules?.[graphId]?.[nodeId]
    if (Array.isArray(handlers)) output.push({ event, graphId, nodeId, handlers })
  }
  return output
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
  if (action === 'context.append_file') return ''
  return ''
}

export function actionLabel(action: string) {
  return RUNTIME_EVENT_ACTION_LABELS[action] || action
}

export function ensureCompanionReceiverGroup(config: RuntimeEventConfig, groupId: string) {
  if (!groupId || groupId in config.receiver_groups) return
  config.receiver_groups[groupId] = {
    enabled: true,
    graph_id: 'Companion',
    merge_target: {
      graph_id: 'Companion',
      node_id: 'Companion',
    },
    receivers: [],
  }
}

export function makeRuntimeEventRule(payload: {
  event: string
  action: string
  target: string
  enabled?: boolean
  params?: RuntimeEventRule['params']
}): RuntimeEventRule {
  const params = payload.params || {}
  return {
    enabled: payload.enabled !== false,
    action: payload.action,
    target: payload.target,
    params: Object.keys(params).length ? params : {},
  }
}

export function addRuntimeEventNode(
  config: RuntimeEventConfig,
  payload: {
    graphId: string
    nodeId: string
    event: string
    handlers?: RuntimeEventRule[]
  },
) {
  if (!config.rules) config.rules = {}
  const eventRules = config.rules[payload.event] || {}
  const graphRules = eventRules[payload.graphId] || {}
  graphRules[payload.nodeId] = [...(payload.handlers || [])]
  eventRules[payload.graphId] = graphRules
  config.rules[payload.event] = eventRules
}

export function addRuntimeEventHandler(
  config: RuntimeEventConfig,
  payload: {
    graphId: string
    nodeId: string
    event: string
    handler: RuntimeEventRule
  },
) {
  const eventRules = config.rules?.[payload.event]
  const graphRules = eventRules?.[payload.graphId]
  if (!graphRules) return false
  const handlers = graphRules[payload.nodeId]
  if (!Array.isArray(handlers)) return false
  graphRules[payload.nodeId] = [...handlers, payload.handler]
  return true
}

export function replaceRuntimeEventHandler(
  config: RuntimeEventConfig,
  payload: {
    graphId: string
    nodeId: string
    event: string
    handlerIndex: number
    handler: RuntimeEventRule
  },
) {
  const eventRules = config.rules?.[payload.event]
  const graphRules = eventRules?.[payload.graphId]
  if (!graphRules) return false
  const handlers = graphRules[payload.nodeId]
  if (!Array.isArray(handlers) || payload.handlerIndex < 0 || payload.handlerIndex >= handlers.length) return false
  const nextHandlers = [...handlers]
  nextHandlers[payload.handlerIndex] = payload.handler
  graphRules[payload.nodeId] = nextHandlers
  return true
}

export function deleteRuntimeEventHandler(
  config: RuntimeEventConfig,
  payload: { graphId: string; nodeId: string; event: string; handlerIndex: number },
) {
  const graphRules = config.rules?.[payload.event]?.[payload.graphId]
  if (!graphRules) return
  const handlers = graphRules[payload.nodeId]
  if (!Array.isArray(handlers)) return
  graphRules[payload.nodeId] = handlers.filter((_handler, index) => index !== payload.handlerIndex)
}

export function deleteRuntimeEventNode(
  config: RuntimeEventConfig,
  payload: { graphId: string; nodeId: string; event: string },
) {
  const eventRules = config.rules?.[payload.event]
  const graphRules = eventRules?.[payload.graphId]
  if (!graphRules) return
  delete graphRules[payload.nodeId]
  if (!Object.keys(graphRules).length) delete eventRules[payload.graphId]
  if (eventRules && !Object.keys(eventRules).length) delete config.rules[payload.event]
}

export function flattenRules(rules: RuntimeEventRules) {
  const output: Array<{
    event: string
    graphId: string
    nodeId: string
    handler: RuntimeEventRule
    handlerIndex: number
  }> = []
  for (const [event, eventRules] of Object.entries(rules || {})) {
    if (!eventRules || typeof eventRules !== 'object' || Array.isArray(eventRules)) continue
    for (const [graphId, graphRules] of Object.entries(eventRules)) {
      if (!graphRules || typeof graphRules !== 'object' || Array.isArray(graphRules)) continue
      for (const [nodeId, nodeRules] of Object.entries(graphRules)) {
        if (!Array.isArray(nodeRules)) continue
        nodeRules.forEach((handler, handlerIndex) => {
          output.push({ event, graphId, nodeId, handler, handlerIndex })
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
  const rawRules = objectMap(value)
  const output: RuntimeEventRules = {}
  for (const [event, eventRules] of Object.entries(rawRules)) {
    if (!eventRules || typeof eventRules !== 'object' || Array.isArray(eventRules)) continue
    for (const [graphId, graphRules] of Object.entries(eventRules as Record<string, unknown>)) {
      if (!graphRules || typeof graphRules !== 'object' || Array.isArray(graphRules)) continue
      for (const [nodeId, nodeRules] of Object.entries(graphRules as Record<string, unknown>)) {
        if (!Array.isArray(nodeRules)) continue
        const handlers = nodeRules.filter((item): item is RuntimeEventRule => !!item && typeof item === 'object' && !Array.isArray(item))
        if (!output[event]) output[event] = {}
        if (!output[event][graphId]) output[event][graphId] = {}
        output[event][graphId][nodeId] = handlers
      }
    }
  }
  return output
}
