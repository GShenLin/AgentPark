import type { GraphConfig, MessageEnvelope, NodeInstanceConfig, NodeInstanceState, PasteAgentConfig } from '../../api'
import type { LinkEndpoint, LinkItem, NodeCard } from './context'
import { normalizeRuntimeEvent, normalizeRuntimeEvents, normalizeRuntimeToolCalls } from './toolRuntimeEvents'

export type SwitchState = 'enabled' | 'disabled'

export type BoardNodePlacement =
  | { kind: 'selection-anchor' }
  | {
      kind: 'fixed'
      ui: { x: number; y: number }
    }

export function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export function clampX(value: number) {
  return Math.max(0, value)
}

export function sanitizeBoardPoint(ui: { x: number; y: number }) {
  return {
    x: clampX(Number(ui?.x ?? 0)),
    y: Math.max(0, Number(ui?.y ?? 0)),
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
  const text = String(value ?? '').trim().toLowerCase()
  if (['enabled', 'enable', 'on', 'true', '1', 'yes'].includes(text)) return 'enabled'
  if (['disabled', 'disable', 'off', 'false', '0', 'no'].includes(text)) return 'disabled'
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
    const key = value.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
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

export function createNodeCardFromConfig(cfg: NodeInstanceConfig, ui: { x: number; y: number }): NodeCard {
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
    providerId: String((cfg as any)?.provider_id ?? '').trim(),
    mode: String((cfg as any)?.mode ?? '').trim(),
    webSearch: normalizeSwitch((cfg as any)?.web_search, 'disabled'),
    thinking: normalizeSwitch((cfg as any)?.thinking, 'enabled'),
    reasoningEffort: (cfg as any)?.reasoning_effort ?? 'high',
    systemPrompt: String((cfg as any)?.system_prompt ?? ''),
    plugins: normalizeConfigList((cfg as any)?.plugins),
    tools: normalizeConfigList((cfg as any)?.tools),
    mcpServers: normalizeConfigList((cfg as any)?.mcp_servers),
    workingPath: String((cfg as any)?.working_path ?? '').trim(),
  }
}

export function applyNodeConfigToCard(node: NodeCard, cfg: NodeInstanceConfig, ui?: { x: number; y: number }) {
  const nodeId = String(cfg.node_id || node.id || '').trim()
  const typeId = String((cfg as any)?.type_id || '').trim()
  node.typeId = typeId || node.typeId || 'echo_node'
  node.name = String((cfg as any)?.name || node.name || nodeId)
  node.inputNum = normalizePortCount((cfg as any)?.input_num, node.inputNum || 1)
  node.outputNum = normalizePortCount((cfg as any)?.output_num, node.outputNum || 1)
  if (ui) {
    node.ui.x = ui.x
    node.ui.y = ui.y
  }
  node.providerId = String((cfg as any)?.provider_id ?? node.providerId ?? '').trim()
  node.mode = String((cfg as any)?.mode ?? node.mode ?? '').trim()
  node.webSearch = normalizeSwitch((cfg as any)?.web_search ?? node.webSearch, 'disabled')
  node.thinking = normalizeSwitch((cfg as any)?.thinking ?? node.thinking, 'enabled')
  node.reasoningEffort = (cfg as any)?.reasoning_effort ?? node.reasoningEffort ?? 'high'
  node.systemPrompt = String((cfg as any)?.system_prompt ?? node.systemPrompt ?? '')
  node.plugins = Array.isArray((cfg as any)?.plugins) ? normalizeConfigList((cfg as any).plugins) : node.plugins || []
  node.tools = Array.isArray((cfg as any)?.tools) ? normalizeConfigList((cfg as any).tools) : node.tools || []
  node.mcpServers = Array.isArray((cfg as any)?.mcp_servers) ? normalizeConfigList((cfg as any).mcp_servers) : node.mcpServers || []
  node.workingPath = String((cfg as any)?.working_path ?? node.workingPath ?? '').trim()
  node.lastRuntimeEvent = normalizeRuntimeEvent((cfg as any)?.last_runtime_event)
  node.runtimeEvents = normalizeRuntimeEvents((cfg as any)?.runtime_events)
  node.runtimeToolCalls = normalizeRuntimeToolCalls((cfg as any)?.runtime_tool_calls)
  node.providerRequestSummaries = normalizeProviderRequestSummaries((cfg as any)?.provider_request_summaries)
}

export function applyNodeConfigOutputToCard(node: NodeCard, cfg: NodeInstanceConfig, out: string) {
  node.last_message = out
  node.lastRuntimeEvent = normalizeRuntimeEvent((cfg as any)?.last_runtime_event)
  node.runtimeEvents = normalizeRuntimeEvents((cfg as any)?.runtime_events)
  node.runtimeToolCalls = normalizeRuntimeToolCalls((cfg as any)?.runtime_tool_calls)
  node.providerRequestSummaries = normalizeProviderRequestSummaries((cfg as any)?.provider_request_summaries)
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
}

function hasOwn(value: object, key: string) {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function normalizeConfigList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item: unknown) => String(item)) : []
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
  nodes: NodeCard[]
  links: LinkItem[]
}): GraphConfig {
  return {
    id: options.graphId || 'default',
    name: options.graphName || 'default',
    nodes: options.nodes.map((node) => ({
      id: node.id,
      typeId: node.typeId,
      name: node.name,
      input_num: normalizePortCount(node.inputNum, 1),
      output_num: normalizePortCount(node.outputNum, 1),
      ui: { x: node.ui.x, y: node.ui.y },
      providerId: node.providerId,
      mode: node.mode,
      web_search: node.webSearch,
      thinking: node.thinking,
      reasoning_effort: node.reasoningEffort,
      systemPrompt: node.systemPrompt,
      plugins: node.plugins,
      tools: node.tools,
      mcpServers: node.mcpServers,
      workingPath: node.workingPath,
    })),
    links: dedupeLinks(
      options.links.map((link) => ({
        id: link.id,
        from: { node: link.from.node, index: normalizePortIndex(link.from.index, 0) },
        to: { node: link.to.node, index: normalizePortIndex(link.to.index, 0) },
      })),
    ),
  }
}

export function normalizeGraphLinks(rawLinks: unknown): LinkItem[] {
  if (!Array.isArray(rawLinks)) return []
  return dedupeLinks(
    rawLinks
      .map((link) => {
        const item = (link || {}) as any
        const fromRaw = item.from
        const toRaw = item.to
        let fromNode = ''
        let toNode = ''
        let fromIndex = 0
        let toIndex = 0

        if (fromRaw && typeof fromRaw === 'object') {
          fromNode = String(fromRaw.node || '').trim()
          fromIndex = normalizePortIndex(fromRaw.index, 0)
        } else {
          fromNode = String(fromRaw || '').trim()
        }

        if (toRaw && typeof toRaw === 'object') {
          toNode = String(toRaw.node || '').trim()
          toIndex = normalizePortIndex(toRaw.index, 0)
        } else {
          toNode = String(toRaw || '').trim()
        }

        return {
          id: item.id,
          from: { node: fromNode, index: fromIndex },
          to: { node: toNode, index: toIndex },
        }
      })
      .filter((link) => link.from.node && link.to.node),
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
