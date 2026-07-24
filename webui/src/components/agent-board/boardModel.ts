import type { GraphConfig, GraphOutputRoutes, MessageEnvelope, NodeInstanceConfig, NodeInstanceState, PasteAgentConfig, ProviderRequestTotals } from '../../api'
import type { LinkEndpoint, LinkItem, NodeCard } from './context'
import { normalizeRuntimeEvent, normalizeRuntimeEvents, normalizeRuntimeToolCalls } from './toolRuntimeEvents'

export type SwitchState = 'enabled' | 'disabled'
export const NODE_CARD_DEFAULT_WIDTH = 230
export const NODE_CARD_DEFAULT_HEIGHT = 250
export const NODE_CARD_MIN_WIDTH = 230
export const NODE_CARD_MIN_HEIGHT = 250
export const NODE_CARD_MAX_WIDTH = 720
export const NODE_CARD_MAX_HEIGHT = 760

export type BoardNodePlacement =
  | { kind: 'selection-anchor' }
  | {
      kind: 'fixed'
      ui: { x: number; y: number; width?: number; height?: number }
    }

export function clampX(value: number) {
  return Math.max(0, value)
}

function boundedNumber(value: unknown, fallback: number, min: number, max: number) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.max(min, Math.min(max, parsed))
}

export function nodeCardWidth(node: NodeCard | undefined) {
  return boundedNumber(node?.ui?.width, NODE_CARD_DEFAULT_WIDTH, NODE_CARD_MIN_WIDTH, NODE_CARD_MAX_WIDTH)
}

export function nodeCardHeight(node: NodeCard | undefined) {
  return boundedNumber(node?.ui?.height, NODE_CARD_DEFAULT_HEIGHT, NODE_CARD_MIN_HEIGHT, NODE_CARD_MAX_HEIGHT)
}

export function sanitizeBoardPoint(ui: { x: number; y: number; width?: number; height?: number }) {
  const width = ui?.width == null ? undefined : Math.round(boundedNumber(ui.width, NODE_CARD_DEFAULT_WIDTH, NODE_CARD_MIN_WIDTH, NODE_CARD_MAX_WIDTH))
  const height = ui?.height == null ? undefined : Math.round(boundedNumber(ui.height, NODE_CARD_DEFAULT_HEIGHT, NODE_CARD_MIN_HEIGHT, NODE_CARD_MAX_HEIGHT))
  return {
    x: clampX(Number(ui?.x ?? 0)),
    y: Math.max(0, Number(ui?.y ?? 0)),
    ...(width == null ? {} : { width }),
    ...(height == null ? {} : { height }),
  }
}

export function normalizePortCount(value: unknown, fallback = 1) {
  const num = Number(value)
  if (!Number.isFinite(num)) return fallback
  const intNum = Math.floor(num)
  return intNum > 0 ? intNum : fallback
}

export function normalizePortIndex(value: unknown, fallback = 0) {
  const num = Number(value)
  if (!Number.isFinite(num)) return fallback
  const intNum = Math.floor(num)
  return intNum >= 0 ? intNum : fallback
}

export function normalizeSwitch(value: unknown, fallback: SwitchState): SwitchState {
  const text = String(value ?? '').trim()
  if (text === 'enabled') return 'enabled'
  if (text === 'disabled') return 'disabled'
  return fallback
}

export type ReasoningEffort = string

export function normalizePasteAgentConfig(raw: PasteAgentConfig | null | undefined): PasteAgentConfig {
  const cfg = raw || ({} as PasteAgentConfig)
  const toolsRaw = Array.isArray(cfg.tools) ? cfg.tools : []
  const safeTools: string[] = []
  const seen = new Set<string>()
  for (const item of toolsRaw) {
    const value = String(item || '').trim()
    if (!value) continue
    if (seen.has(value)) continue
    seen.add(value)
    safeTools.push(value)
  }
  return {
    agent_id: String(cfg.agent_id || 'pastagent').trim() || 'pastagent',
    name: String(cfg.name || 'PasteAgent').trim() || 'PasteAgent',
    provider_id: String(cfg.provider_id || '').trim(),
    mode: String(cfg.mode || 'chat').trim() || 'chat',
    web_search: normalizeSwitch(cfg.web_search, 'enabled'),
    thinking: normalizeSwitch(cfg.thinking, 'enabled'),
    reasoning_effort: (cfg as any).reasoning_effort ?? 'high',
    system_prompt: String(cfg.system_prompt || ''),
    tools: safeTools,
  }
}

export function nodeStateFromConfig(cfg: NodeInstanceConfig): NodeInstanceState {
  const state = cfg.state
  return state === 'working' || state === 'stop' ? state : 'idle'
}

export function nodeConfigRunDelta(prev: NodeInstanceConfig | undefined, next: NodeInstanceConfig) {
  const prevRunAt = prev?.last_run_at != null ? String(prev.last_run_at) : ''
  const runAt = (next as any)?.last_run_at != null ? String((next as any).last_run_at) : ''
  const prevOut = prev?.last_message != null ? String(prev.last_message) : ''
  const out = (next as any)?.last_message != null ? String((next as any).last_message) : ''
  return {
    runAt,
    out,
    runAtChanged: runAt !== prevRunAt,
    outputChanged: out !== prevOut,
  }
}

export function normalizeProviderRequestSummaries(value: unknown) {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') : []
}

export function normalizeProviderRequestTotals(value: unknown): ProviderRequestTotals | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Record<string, unknown>
  return {
    request_count: normalizeNonNegativeInt(item.request_count),
    approx_input_chars: normalizeNonNegativeInt(item.approx_input_chars),
    approx_input_tokens: normalizeNonNegativeInt(item.approx_input_tokens),
    tool_call_chars: normalizeNonNegativeInt(item.tool_call_chars),
    tool_result_chars: normalizeNonNegativeInt(item.tool_result_chars),
    last_request_index: normalizeNonNegativeInt(item.last_request_index),
    completed_request_count: normalizeNonNegativeInt(item.completed_request_count),
    last_completed_request_index: normalizeNonNegativeInt(item.last_completed_request_index),
    actual_input_tokens: normalizeNonNegativeInt(item.actual_input_tokens),
    actual_output_tokens: normalizeNonNegativeInt(item.actual_output_tokens),
    actual_total_tokens: normalizeNonNegativeInt(item.actual_total_tokens),
    actual_cached_input_tokens: normalizeNonNegativeInt(item.actual_cached_input_tokens),
    actual_cache_write_input_tokens: normalizeNonNegativeInt(item.actual_cache_write_input_tokens),
    actual_reasoning_output_tokens: normalizeNonNegativeInt(item.actual_reasoning_output_tokens),
  }
}

export function createNodeCardFromConfig(cfg: NodeInstanceConfig, ui: { x: number; y: number; width?: number; height?: number }): NodeCard {
  const nodeId = String(cfg.node_id || '').trim()
  const typeId = String((cfg as any)?.type_id || '').trim()
  return {
    id: nodeId,
    typeId: typeId || 'echo_node',
    name: String((cfg as any)?.name || nodeId),
    inputNum: normalizePortCount((cfg as any)?.input_num, 1),
    outputNum: normalizePortCount((cfg as any)?.output_num, 1),
    ui,
    last_message: String((cfg as any)?.last_message ?? '') || null,
    lastRuntimeEvent: normalizeRuntimeEvent((cfg as any)?.last_runtime_event),
    runtimeEvents: normalizeRuntimeEvents((cfg as any)?.runtime_events),
    runtimeToolCalls: normalizeRuntimeToolCalls((cfg as any)?.runtime_tool_calls),
    providerRequestSummaries: normalizeProviderRequestSummaries((cfg as any)?.provider_request_summaries),
    providerRequestTotals: normalizeProviderRequestTotals((cfg as any)?.provider_request_totals),
    providerId: String((cfg as any)?.provider_id ?? '').trim(),
    mode: String((cfg as any)?.mode ?? '').trim(),
    webSearch: normalizeSwitch((cfg as any)?.web_search, 'disabled'),
    thinking: normalizeSwitch((cfg as any)?.thinking, 'enabled'),
    reasoningEffort: (cfg as any)?.reasoning_effort ?? 'high',
    instruction: String((cfg as any)?.instruction ?? ''),
    systemPrompt: String((cfg as any)?.system_prompt ?? ''),
    plugins: normalizeConfigList((cfg as any)?.plugins),
    tools: normalizeConfigList((cfg as any)?.tools),
    mcpServers: normalizeConfigList((cfg as any)?.mcp_servers),
    workingPath: String((cfg as any)?.working_path ?? '').trim(),
    remoteEnabled: Boolean((cfg as any)?.remote_enabled),
    remoteWorkerId: String((cfg as any)?.remote_worker_id ?? '').trim(),
  }
}

export function applyNodeConfigToCard(node: NodeCard, cfg: NodeInstanceConfig, ui?: { x: number; y: number; width?: number; height?: number }) {
  const nodeId = String(cfg.node_id || node.id || '').trim()
  const typeId = String((cfg as any)?.type_id || '').trim()
  node.typeId = typeId || node.typeId || 'echo_node'
  node.name = String((cfg as any)?.name || node.name || nodeId)
  node.inputNum = normalizePortCount((cfg as any)?.input_num, node.inputNum || 1)
  node.outputNum = normalizePortCount((cfg as any)?.output_num, node.outputNum || 1)
  if (ui) {
    const normalizedUi = sanitizeBoardPoint(ui)
    node.ui.x = normalizedUi.x
    node.ui.y = normalizedUi.y
    if (normalizedUi.width != null) node.ui.width = normalizedUi.width
    if (normalizedUi.height != null) node.ui.height = normalizedUi.height
  }
  node.providerId = String((cfg as any)?.provider_id ?? node.providerId ?? '').trim()
  node.mode = String((cfg as any)?.mode ?? node.mode ?? '').trim()
  node.webSearch = normalizeSwitch((cfg as any)?.web_search ?? node.webSearch, 'disabled')
  node.thinking = normalizeSwitch((cfg as any)?.thinking ?? node.thinking, 'enabled')
  node.reasoningEffort = (cfg as any)?.reasoning_effort ?? node.reasoningEffort ?? 'high'
  node.instruction = String((cfg as any)?.instruction ?? node.instruction ?? '')
  node.systemPrompt = String((cfg as any)?.system_prompt ?? node.systemPrompt ?? '')
  node.plugins = Array.isArray((cfg as any)?.plugins) ? normalizeConfigList((cfg as any).plugins) : node.plugins || []
  node.tools = Array.isArray((cfg as any)?.tools) ? normalizeConfigList((cfg as any).tools) : node.tools || []
  node.mcpServers = Array.isArray((cfg as any)?.mcp_servers) ? normalizeConfigList((cfg as any).mcp_servers) : node.mcpServers || []
  node.workingPath = String((cfg as any)?.working_path ?? node.workingPath ?? '').trim()
  node.remoteEnabled = Boolean((cfg as any)?.remote_enabled ?? node.remoteEnabled)
  node.remoteWorkerId = String((cfg as any)?.remote_worker_id ?? node.remoteWorkerId ?? '').trim()
  node.lastRuntimeEvent = normalizeRuntimeEvent((cfg as any)?.last_runtime_event)
  node.runtimeEvents = normalizeRuntimeEvents((cfg as any)?.runtime_events)
  node.runtimeToolCalls = normalizeRuntimeToolCalls((cfg as any)?.runtime_tool_calls)
  node.providerRequestSummaries = normalizeProviderRequestSummaries((cfg as any)?.provider_request_summaries)
  node.providerRequestTotals = normalizeProviderRequestTotals((cfg as any)?.provider_request_totals)
}

export function applyNodeConfigOutputToCard(node: NodeCard, cfg: NodeInstanceConfig, out: string) {
  node.last_message = out
  node.lastRuntimeEvent = normalizeRuntimeEvent((cfg as any)?.last_runtime_event)
  node.runtimeEvents = normalizeRuntimeEvents((cfg as any)?.runtime_events)
  node.runtimeToolCalls = normalizeRuntimeToolCalls((cfg as any)?.runtime_tool_calls)
  node.providerRequestSummaries = normalizeProviderRequestSummaries((cfg as any)?.provider_request_summaries)
  node.providerRequestTotals = normalizeProviderRequestTotals((cfg as any)?.provider_request_totals)
}

export function mergeNodeConfigFields(options: {
  nodeId: string
  graphId: string
  existing?: NodeInstanceConfig
  fallbackTypeId?: string
  fallbackName?: string
  fields: Record<string, unknown>
}): NodeInstanceConfig {
  const base = options.existing || ({
    node_id: options.nodeId,
    type_id: options.fallbackTypeId || '',
    name: options.fallbackName || '',
    graph_id: options.graphId,
  } as NodeInstanceConfig)
  return {
    ...base,
    type_id: String((base as any)?.type_id || options.fallbackTypeId || ''),
    ...options.fields,
  } as NodeInstanceConfig
}

export function applyNodeFieldPatchToCard(
  node: NodeCard,
  merged: NodeInstanceConfig,
  fields: Record<string, unknown>,
) {
  if (hasOwn(fields, 'provider_id')) {
    node.providerId = String((merged as any)?.provider_id ?? '').trim()
  }
  if (hasOwn(fields, 'mode')) {
    node.mode = String((merged as any)?.mode ?? '').trim()
  }
  if (hasOwn(fields, 'web_search')) {
    node.webSearch = normalizeSwitch((merged as any)?.web_search, 'disabled')
  }
  if (hasOwn(fields, 'thinking')) {
    node.thinking = normalizeSwitch((merged as any)?.thinking, 'enabled')
  }
  if (hasOwn(fields, 'reasoning_effort')) {
    node.reasoningEffort = String((merged as any)?.reasoning_effort ?? '')
  }
  if (hasOwn(fields, 'instruction')) {
    node.instruction = String((merged as any)?.instruction ?? '')
  }
  if (hasOwn(fields, 'system_prompt')) {
    node.systemPrompt = String((merged as any)?.system_prompt ?? '')
  }
  if (hasOwn(fields, 'plugins')) {
    node.plugins = normalizeConfigList((merged as any)?.plugins)
  }
  if (hasOwn(fields, 'tools')) {
    node.tools = normalizeConfigList((merged as any)?.tools)
  }
  if (hasOwn(fields, 'mcp_servers')) {
    node.mcpServers = normalizeConfigList((merged as any)?.mcp_servers)
  }
  if (hasOwn(fields, 'working_path')) {
    node.workingPath = String((merged as any)?.working_path ?? '').trim()
  }
  if (hasOwn(fields, 'remote_enabled')) {
    node.remoteEnabled = Boolean((merged as any)?.remote_enabled)
  }
  if (hasOwn(fields, 'remote_worker_id')) {
    node.remoteWorkerId = String((merged as any)?.remote_worker_id ?? '').trim()
  }
}

function hasOwn(value: object, key: string) {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function normalizeConfigList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const result: string[] = []
  const seen = new Set<string>()
  for (const item of value) {
    if (typeof item !== 'string') continue
    const text = item.trim()
    if (!text || seen.has(text)) continue
    seen.add(text)
    result.push(text)
  }
  return result
}

function normalizeNonNegativeInt(value: unknown) {
  const numberValue = Number(value)
  if (!Number.isFinite(numberValue)) return undefined
  return Math.max(0, Math.round(numberValue))
}

export function previewMessage(value: string | null) {
  const text = String(value ?? '').trim()
  if (!text) return ''
  return text.length > 64 ? `${text.slice(0, 64)}...` : text
}

export function messageToText(value: string | MessageEnvelope) {
  if (typeof value === 'string') return value
  const parts = Array.isArray(value?.parts) ? value.parts : []
  const output: string[] = []
  for (const part of parts) {
    if (!part || typeof part !== 'object') continue
    const typ = String((part as any).type || '').toLowerCase()
    if (typ === 'text') {
      const text = String((part as any).text || '')
      if (text) output.push(text)
    } else if (typ === 'resource') {
      const res = (part as any).resource || {}
      const kind = String(res.kind || 'file')
      const uri = String(res.uri || '')
      if (uri) output.push(`[${kind}] ${uri}`)
    }
  }
  return output.join('\n').trim()
}

export function linkKey(from: LinkEndpoint, to: LinkEndpoint) {
  return `${from.node}:${from.index}->${to.node}:${to.index}`
}

export function dedupeLinks<T extends Pick<LinkItem, 'id' | 'from' | 'to'>>(items: T[]) {
  const seen = new Set<string>()
  const out: T[] = []
  for (const link of items) {
    const key = linkKey(link.from, link.to)
    if (seen.has(key)) continue
    seen.add(key)
    out.push(link)
  }
  return out
}

export function buildBoardGraphConfig(options: {
  graphId: string
  graphName: string
  workingPath?: string
  nodes: NodeCard[]
  links: LinkItem[]
}): GraphConfig {
  return {
    id: options.graphId || 'default',
    name: options.graphName || 'default',
    working_path: String(options.workingPath || '').trim(),
    nodes: options.nodes.map((node) => ({
      id: node.id,
      typeId: node.typeId,
      name: node.name,
      input_num: normalizePortCount(node.inputNum, 1),
      output_num: normalizePortCount(node.outputNum, 1),
      ui: sanitizeBoardPoint(node.ui),
      providerId: node.providerId,
      mode: node.mode,
      web_search: node.webSearch,
      thinking: node.thinking,
      reasoning_effort: node.reasoningEffort,
      instruction: node.instruction,
      systemPrompt: node.systemPrompt,
      plugins: node.plugins,
      tools: node.tools,
      mcpServers: node.mcpServers,
      workingPath: node.workingPath,
      remoteEnabled: node.remoteEnabled,
      remoteWorkerId: node.remoteWorkerId,
    })),
    output_routes: buildOutputRoutesFromLinks(options.links),
  }
}

export function buildOutputRoutesFromLinks(links: LinkItem[]): GraphOutputRoutes {
  const routeMap = new Map<string, { output_index: number; targets: Array<{ node_id: string; input_index: number }> }>()
  for (const link of dedupeLinks(links)) {
    const sourceId = String(link.from.node || '').trim()
    const targetId = String(link.to.node || '').trim()
    if (!sourceId || !targetId) continue
    const outputIndex = normalizePortIndex(link.from.index, 0)
    const inputIndex = normalizePortIndex(link.to.index, 0)
    const key = `${sourceId}:${outputIndex}`
    const route = routeMap.get(key) || { output_index: outputIndex, targets: [] }
    if (!route.targets.some((target) => target.node_id === targetId && target.input_index === inputIndex)) {
      route.targets.push({ node_id: targetId, input_index: inputIndex })
    }
    routeMap.set(key, route)
  }

  const outputRoutes: GraphOutputRoutes = {}
  for (const [key, route] of routeMap.entries()) {
    const sourceId = key.split(':')[0] || ''
    if (!sourceId) continue
    const items = outputRoutes[sourceId] || []
    items.push(route)
    outputRoutes[sourceId] = items
  }
  for (const sourceId of Object.keys(outputRoutes)) {
    const items = outputRoutes[sourceId]
    if (!items) continue
    items.sort(
      (a: { output_index: number }, b: { output_index: number }) => a.output_index - b.output_index,
    )
  }
  return outputRoutes
}

export function normalizeGraphLinks(rawRoutes: unknown): LinkItem[] {
  if (!rawRoutes || typeof rawRoutes !== 'object' || Array.isArray(rawRoutes)) return []
  const routeRecord = rawRoutes as Record<string, unknown>
  const projectedLinks: LinkItem[] = []
  for (const [sourceIdRaw, routesRaw] of Object.entries(routeRecord)) {
    const sourceId = String(sourceIdRaw || '').trim()
    if (!sourceId || !Array.isArray(routesRaw)) continue
    for (const route of routesRaw) {
      if (!route || typeof route !== 'object') continue
      const outputIndex = normalizePortIndex((route as any).output_index, 0)
      const targets = (route as any).targets
      if (!Array.isArray(targets)) continue
      for (const target of targets) {
        if (!target || typeof target !== 'object') continue
        const targetId = String((target as any).node_id || '').trim()
        if (!targetId) continue
        const inputIndex = normalizePortIndex((target as any).input_index, 0)
        projectedLinks.push({
          id: `route-${sourceId}-${outputIndex}-${targetId}-${inputIndex}`,
          from: { node: sourceId, index: outputIndex },
          to: { node: targetId, index: inputIndex },
        })
      }
    }
  }
  return dedupeLinks(
    projectedLinks.filter((link) => link.from.node && link.to.node),
  )
}

export function getNodePortPosition(options: {
  node: NodeCard | undefined
  side: 'input' | 'output'
  portIndex?: number
  cardWidth: number
  cardHeight: number
  portRadius: number
}) {
  const node = options.node
  if (!node) return null
  const portCount =
    options.side === 'input'
      ? normalizePortCount(node.inputNum, 1)
      : normalizePortCount(node.outputNum, 1)
  const index = normalizePortIndex(options.portIndex, 0)
  const safeIndex = Math.min(Math.max(0, index), portCount - 1)
  const ratio = (safeIndex + 0.5) / portCount
  const offsetX = options.side === 'input' ? -options.portRadius : options.cardWidth + options.portRadius
  return {
    x: node.ui.x + offsetX,
    y: node.ui.y + options.cardHeight * ratio,
  }
}

export function buildLinkPath(start: { x: number; y: number }, end: { x: number; y: number }) {
  const dx = end.x - start.x
  const c1 = start.x + dx * 0.4
  const c2 = start.x + dx * 0.6
  return `M ${start.x} ${start.y} C ${c1} ${start.y}, ${c2} ${end.y}, ${end.x} ${end.y}`
}

export function pruneLinksForNodePorts(options: {
  links: LinkItem[]
  nodeId: string
  inputNum: unknown
  outputNum: unknown
}) {
  const maxInputs = normalizePortCount(options.inputNum, 1)
  const maxOutputs = normalizePortCount(options.outputNum, 1)
  return options.links.filter((link) => {
    if (link.from.node === options.nodeId && normalizePortIndex(link.from.index, 0) >= maxOutputs) {
      return false
    }
    if (link.to.node === options.nodeId && normalizePortIndex(link.to.index, 0) >= maxInputs) {
      return false
    }
    return true
  })
}
