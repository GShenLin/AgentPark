<script setup lang="ts">
import { marked } from 'marked'
import type { MessageEnvelope } from '../api'
import MemoryResourcePart from './MemoryResourcePart.vue'
import MemoryToolCallPart from './MemoryToolCallPart.vue'

defineProps<{
  messages: MessageEnvelope[]
  markdownPreview: boolean
}>()

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function normalizeMemoryRole(role: string) {
  const value = String(role || '').trim().toLowerCase()
  if (!value) return 'other'
  if (value.includes('user') || value.includes('human')) return 'user'
  if (value.includes('assistant') || value.includes('agent')) return 'assistant'
  if (value.includes('system')) return 'system'
  if (value.includes('commentary') || value.includes('reasoning')) return 'commentary'
  if (value.includes('tool')) return 'tool'
  const safe = value.replace(/[^a-z0-9_-]/g, '')
  return safe || 'other'
}

function memoryRoleLabel(roleKey: string, rawRole: string) {
  if (roleKey === 'user') return 'User'
  if (roleKey === 'assistant') return 'Assistant'
  if (roleKey === 'system') return 'System'
  if (roleKey === 'commentary') return 'Commentary'
  if (roleKey === 'tool') return 'Tool'
  const text = String(rawRole || '').trim()
  return text || 'Other'
}

function feedRoleClass(role: string) {
  const key = normalizeMemoryRole(role)
  if (key === 'user' || key === 'assistant' || key === 'system' || key === 'commentary' || key === 'tool') return key
  return 'other'
}

function shouldRenderMarkdownForRole(role: string) {
  const roleKey = normalizeMemoryRole(role)
  return roleKey !== 'user'
}

function renderFeedMarkdown(text: string) {
  const raw = String(text || '')
  if (!raw) return ''
  try {
    return marked.parse(raw)
  } catch {
    return `<pre>${escapeHtml(raw)}</pre>`
  }
}

</script>

<template>
  <template v-if="messages.length > 0">
    <div
      v-for="(msg, msgIndex) in messages"
      :key="String((msg as any)?.id || msgIndex)"
      class="feed-item"
      :class="`role-${feedRoleClass(String((msg as any)?.role || 'assistant'))}`"
    >
      <div class="feed-head">
        <span class="feed-role">{{ memoryRoleLabel(feedRoleClass(String((msg as any)?.role || 'assistant')), String((msg as any)?.role || '')) }}</span>
        <span class="feed-time">{{ String((msg as any)?.created_at || '') }}</span>
      </div>
      <div class="feed-parts">
        <template v-for="(part, idx) in ((msg as any)?.parts || [])" :key="`${String((msg as any)?.id || '')}-${idx}`">
          <div
            v-if="String((part as any)?.type || '') === 'text' && markdownPreview && shouldRenderMarkdownForRole(String((msg as any)?.role || 'assistant'))"
            class="feed-text markdown-part"
            v-html="renderFeedMarkdown(String((part as any)?.text || ''))"
          ></div>
          <div v-else-if="String((part as any)?.type || '') === 'text'" class="feed-text">{{ String((part as any)?.text || '') }}</div>
          <MemoryResourcePart v-else-if="String((part as any)?.type || '') === 'resource'" :part="part as Record<string, unknown>" />
          <MemoryToolCallPart v-else-if="String((part as any)?.type || '') === 'tool_call'" :part="part as Record<string, unknown>" />
          <pre v-else class="feed-structured">{{ JSON.stringify(part, null, 2) }}</pre>
        </template>
      </div>
    </div>
  </template>
</template>

<style scoped>
.feed-item {
  flex: 0 0 auto;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.45);
  overflow: hidden;
}

.feed-item.role-user {
  border-left: 4px solid rgba(56, 189, 248, 0.65);
}

.feed-item.role-assistant {
  border-left: 4px solid rgba(34, 197, 94, 0.65);
}

.feed-item.role-system {
  border-left: 4px solid rgba(148, 163, 184, 0.6);
}

.feed-item.role-commentary {
  border-left: 4px solid rgba(250, 204, 21, 0.68);
}

.feed-item.role-tool {
  border-left: 4px solid rgba(244, 114, 182, 0.68);
}

.feed-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(0, 0, 0, 0.2);
}

.feed-role {
  font-size: 12px;
  font-weight: 700;
}

.feed-time {
  font-size: 11px;
  color: rgba(148, 163, 184, 0.9);
}

.feed-parts {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.feed-text {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
}

.feed-text.markdown-part {
  white-space: normal;
}

:deep(.feed-text.markdown-part p) {
  margin: 0 0 8px 0;
}

:deep(.feed-text.markdown-part p:last-child) {
  margin-bottom: 0;
}

:deep(.feed-text.markdown-part pre) {
  margin: 8px 0;
  padding: 10px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.28);
  overflow: auto;
}

:deep(.feed-text.markdown-part code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
}

:deep(.feed-text.markdown-part ul),
:deep(.feed-text.markdown-part ol) {
  margin: 6px 0 6px 18px;
  padding: 0;
}

:deep(.feed-text.markdown-part li) {
  margin: 2px 0;
}

.feed-structured {
  margin: 0;
  padding: 8px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.24);
  overflow: auto;
  font-size: 12px;
}
</style>
