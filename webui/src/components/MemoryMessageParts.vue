<script setup lang="ts">
import type { MessageEnvelope } from '../api'
import MemoryMessageActions from './MemoryMessageActions.vue'
import MemoryResourcePart from './MemoryResourcePart.vue'
import MemoryResponseMetadataPart from './MemoryResponseMetadataPart.vue'
import MemoryToolCallPart from './MemoryToolCallPart.vue'
import { handleMarkdownCodeCopyClick } from './markdownCodeCopy'
import { renderMarkdownText } from './memoryMarkdown'
import { extractMemoryMessageText } from './memoryMessageText'
import { messageParts, normalizeMemoryRole } from './memoryFeedTools'

const props = withDefaults(defineProps<{
  message: MessageEnvelope
  markdownPreview: boolean
  showActions?: boolean
}>(), {
  showActions: true,
})

const emit = defineEmits<{
  (event: 'save', text: string): void
  (event: 'copy', text: string): void
  (event: 'delete', message: MessageEnvelope): void
}>()

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function shouldRenderMarkdown() {
  return normalizeMemoryRole(String((props.message as any)?.role || 'assistant')) !== 'user'
}

function renderFeedMarkdown(text: string) {
  let raw = String(text || '')
  if (!raw) return ''
  if (raw.startsWith('returncode:') && raw.includes('--- stdout ---')) {
    raw = '```text\n' + raw + '\n```'
  }
  try {
    return renderMarkdownText(raw)
  } catch {
    return `<pre>${escapeHtml(raw)}</pre>`
  }
}

function isResponseMetadataPart(part: unknown) {
  if (!part || typeof part !== 'object' || String((part as any).type || '') !== 'structured') return false
  const data = (part as any).data
  return !!(data && typeof data === 'object' && (data.response_metadata || Array.isArray(data.server_tool_calls) || Array.isArray(data.citations)))
}

function isAssistantProgressMeta(part: unknown) {
  return !!(part && typeof part === 'object' && String((part as any).type || '') === 'meta' && String((part as any)?.meta?.kind || '') === 'assistant_progress')
}

function messageText() {
  return extractMemoryMessageText(props.message)
}

function canDelete() {
  return !!String((props.message as any)?.id || '').trim()
}
</script>

<template>
  <div class="feed-parts">
    <template v-for="(part, idx) in messageParts(message)" :key="idx">
      <div
        v-if="String((part as any)?.type || '') === 'text' && markdownPreview && shouldRenderMarkdown()"
        class="feed-text markdown-part"
        v-html="renderFeedMarkdown(String((part as any)?.text || ''))"
        @click="handleMarkdownCodeCopyClick"
      ></div>
      <div v-else-if="String((part as any)?.type || '') === 'text'" class="feed-text">{{ String((part as any)?.text || '') }}</div>
      <MemoryResourcePart v-else-if="String((part as any)?.type || '') === 'resource'" :part="part as Record<string, unknown>" />
      <MemoryToolCallPart v-else-if="String((part as any)?.type || '') === 'tool_call'" :part="part as Record<string, unknown>" />
      <MemoryResponseMetadataPart v-else-if="isResponseMetadataPart(part)" :data="(part as any).data" />
      <div v-else-if="isAssistantProgressMeta(part)" class="progress-context-note">Excluded from model context</div>
      <pre v-else class="feed-structured">{{ JSON.stringify(part, null, 2) }}</pre>
    </template>
    <MemoryMessageActions
      v-if="showActions && (messageText() || canDelete())"
      class="feed-actions"
      :show-save="!!messageText()"
      :show-copy="!!messageText()"
      :show-delete="canDelete()"
      @save="emit('save', messageText())"
      @copy="emit('copy', messageText())"
      @delete="emit('delete', message)"
    />
  </div>
</template>

<style scoped>
.feed-parts { padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.feed-actions { align-self: flex-end; margin-top: 2px; }
.feed-text { white-space: pre-wrap; word-break: break-word; line-height: 1.55; }
.feed-text.markdown-part { white-space: normal; }
.progress-context-note { align-self: flex-start; padding: 2px 7px; border-radius: 999px; color: rgba(125, 211, 252, 0.9); background: rgba(14, 116, 144, 0.16); font-size: 11px; }
.feed-structured { margin: 0; padding: 8px; border-radius: 8px; background: rgba(0, 0, 0, 0.24); overflow: auto; font-size: 12px; }
:deep(.feed-text.markdown-part p) { margin: 0 0 8px 0; }
:deep(.feed-text.markdown-part p:last-child) { margin-bottom: 0; }
:deep(.feed-text.markdown-part pre) { margin: 8px 0; padding: 10px; border-radius: 8px; background: rgba(0, 0, 0, 0.28); overflow: auto; }
:deep(.feed-text.markdown-part .markdown-code-block pre) { margin: 0; padding: 10px 48px 34px 10px; background: transparent; }
:deep(.feed-text.markdown-part code) { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace; }
:deep(.feed-text.markdown-part ul), :deep(.feed-text.markdown-part ol) { margin: 6px 0 6px 18px; padding: 0; }
:deep(.feed-text.markdown-part li) { margin: 2px 0; }
</style>
