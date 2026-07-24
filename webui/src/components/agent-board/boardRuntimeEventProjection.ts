import type { NodeInstanceConfig, RuntimeEvent, RuntimeToolCall } from '../../api'


function eventFromGraphPayload(payload: Record<string, unknown>): RuntimeEvent | null {
  const type = String(payload.event || '').trim()
  if (type === 'runtime_notice') {
    const message = String(payload.message || '').trim()
    if (!message) return null
    return {
      type,
      message,
      source: payload.source != null ? String(payload.source) : undefined,
      stage: payload.stage != null ? String(payload.stage) : undefined,
      name: payload.tool_name != null ? String(payload.tool_name) : undefined,
      call_id: payload.call_id != null ? String(payload.call_id) : null,
      provider: payload.provider != null ? String(payload.provider) : null,
    }
  }
  if (type === 'server_tool_activity') {
    const callId = String(payload.call_id || '').trim()
    const toolType = String(payload.tool_name || '').trim()
    if (!callId || !toolType) return null
    return {
      type,
      call_id: callId,
      tool_type: toolType,
      status: String(payload.status || 'in_progress'),
      provider: payload.provider != null ? String(payload.provider) : null,
    }
  }
  if (type !== 'tool_call_start' && type !== 'tool_call_end') return null
  return {
    type,
    name: payload.tool_name != null ? String(payload.tool_name) : undefined,
    call_id: payload.call_id != null ? String(payload.call_id) : null,
    provider: payload.provider != null ? String(payload.provider) : null,
    status: payload.status != null ? String(payload.status) : undefined,
    duration_ms: typeof payload.duration_ms === 'number' ? payload.duration_ms : undefined,
    error: payload.error != null ? String(payload.error) : undefined,
    result_preview: payload.result_preview != null ? String(payload.result_preview) : undefined,
  }
}

function upsertToolCall(calls: RuntimeToolCall[], event: RuntimeEvent): RuntimeToolCall[] {
  if (event.type !== 'tool_call_start' && event.type !== 'tool_call_end') return calls
  const callId = String(event.call_id || '').trim()
  if (!callId) return calls
  const index = calls.findIndex((item) => item.call_id === callId)
  const existing = index >= 0 ? calls[index] : null
  const next: RuntimeToolCall = {
    ...(existing || { call_id: callId, status: 'running' }),
    name: event.name || existing?.name,
    provider: event.provider ?? existing?.provider ?? null,
    status: event.type === 'tool_call_start' ? 'running' : String(event.status || 'completed'),
    duration_ms: event.duration_ms ?? existing?.duration_ms ?? null,
    error: event.error ?? existing?.error ?? null,
    result_preview: event.result_preview ?? existing?.result_preview ?? null,
  }
  const updated = [...calls]
  if (index >= 0) updated[index] = next
  else updated.push(next)
  return updated.slice(-20)
}

export function applyBoardRuntimeEvent(
  config: NodeInstanceConfig,
  payload: Record<string, unknown>,
): NodeInstanceConfig {
  const event = eventFromGraphPayload(payload)
  if (!event) return config
  const runtimeEvents = Array.isArray(config.runtime_events) ? config.runtime_events : []
  const runtimeToolCalls = Array.isArray(config.runtime_tool_calls) ? config.runtime_tool_calls : []
  const providerSummary = payload.provider_request_summary
  return {
    ...config,
    last_runtime_event: event,
    runtime_events: [...runtimeEvents, event].slice(-20),
    runtime_tool_calls: upsertToolCall(runtimeToolCalls, event),
    provider_request_summaries:
      providerSummary && typeof providerSummary === 'object' && !Array.isArray(providerSummary)
        ? [providerSummary]
        : config.provider_request_summaries,
  }
}
