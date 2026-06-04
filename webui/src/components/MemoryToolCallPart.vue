<script setup lang="ts">
defineProps<{
  part: Record<string, unknown>
}>()

function toolCallName(part: Record<string, unknown>) {
  return String(part.name || 'tool').trim() || 'tool'
}

function toolCallStatus(part: Record<string, unknown>) {
  return String(part.status || 'completed').trim() || 'completed'
}

function toolCallMeta(part: Record<string, unknown>) {
  const chunks: string[] = []
  const provider = String(part.provider || '').trim()
  const callId = String(part.call_id || '').trim()
  const duration = part.duration_ms
  if (provider) chunks.push(provider)
  if (callId) chunks.push(callId)
  if (typeof duration === 'number') chunks.push(`${Math.max(0, Math.round(duration))}ms`)
  return chunks.join(' / ')
}

function toolCallPreview(part: Record<string, unknown>) {
  return String(part.error || part.result_preview || '').trim()
}

function toolCallArguments(part: Record<string, unknown>) {
  const args = part.args ?? part.arguments
  if (!args || typeof args !== 'object') return ''
  try {
    return JSON.stringify(args, null, 2)
  } catch {
    return String(args)
  }
}

function toolCallDiagnostics(part: Record<string, unknown>) {
  const diagnostics = part.diagnostics
  if (!Array.isArray(diagnostics)) return []
  return diagnostics.map((item) => String(item)).filter((item) => item.trim())
}
</script>

<template>
  <div class="feed-tool-call">
    <div class="feed-tool-main">
      <span class="feed-tool-dot" :class="`status-${toolCallStatus(part)}`"></span>
      <span class="feed-tool-name">{{ toolCallName(part) }}</span>
      <span class="feed-tool-status">{{ toolCallStatus(part) }}</span>
    </div>
    <div v-if="toolCallMeta(part)" class="feed-tool-meta">{{ toolCallMeta(part) }}</div>
    <pre v-if="toolCallArguments(part)" class="feed-tool-arguments">{{ toolCallArguments(part) }}</pre>
    <div v-if="toolCallPreview(part)" class="feed-tool-preview">{{ toolCallPreview(part) }}</div>
    <div v-if="toolCallDiagnostics(part).length" class="feed-tool-diagnostics">
      <div v-for="(item, index) in toolCallDiagnostics(part)" :key="index" class="feed-tool-diagnostic">
        {{ item }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.feed-tool-call {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-radius: 8px;
  padding: 8px;
  border: 1px solid rgba(244, 114, 182, 0.22);
  background: rgba(83, 22, 54, 0.16);
}

.feed-tool-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.feed-tool-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  flex: 0 0 auto;
  background: rgba(125, 211, 252, 0.95);
}

.feed-tool-dot.status-completed {
  background: rgba(52, 211, 153, 0.95);
}

.feed-tool-dot.status-error,
.feed-tool-dot.status-failed,
.feed-tool-dot.status-timeout {
  background: rgba(248, 113, 113, 0.95);
}

.feed-tool-name {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(248, 250, 252, 0.95);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 12px;
}

.feed-tool-status,
.feed-tool-meta,
.feed-tool-preview {
  color: rgba(203, 213, 225, 0.78);
  font-size: 11px;
}

.feed-tool-status {
  flex: 0 0 auto;
}

.feed-tool-preview {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.feed-tool-arguments {
  margin: 0;
  padding: 7px 8px;
  border-radius: 7px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(2, 6, 23, 0.38);
  color: rgba(203, 213, 225, 0.9);
  font-size: 11px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.feed-tool-diagnostics {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.feed-tool-diagnostic {
  border-left: 2px solid rgba(251, 191, 36, 0.72);
  padding-left: 7px;
  color: rgba(254, 240, 138, 0.88);
  font-size: 11px;
  line-height: 1.35;
  word-break: break-word;
}
</style>
