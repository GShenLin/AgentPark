<script setup lang="ts">
import { ref, toRef } from 'vue'
import type { MessageEnvelope } from '../api'
import MemoryMessageActions from './MemoryMessageActions.vue'
import MemoryResourcePart from './MemoryResourcePart.vue'
import MemoryToolCallPart from './MemoryToolCallPart.vue'
import { extractMemoryMessageText } from './memoryMessageText'
import {
  feedRoleClass,
  memoryRoleLabel,
  messageParts,
  normalizeMemoryRole,
  toolDuration,
  toolGroupLabel,
  toolGroupParts,
  toolGroupTime,
  toolName,
  toolStatus,
  lastToolInstruction,
  useMemoryFeedEntries,
} from './memoryFeedTools'
import { renderMarkdownText } from './memoryMarkdown'

const props = defineProps<{
  messages: MessageEnvelope[]
  markdownPreview: boolean
}>()

const emit = defineEmits<{
  (event: 'saveMessage', text: string): void
  (event: 'copyMessage', text: string): void
}>()

const expandedToolGroups = ref<Set<string>>(new Set())

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function isToolGroupExpanded(key: string) {
  return expandedToolGroups.value.has(key)
}

function toggleToolGroup(key: string) {
  const next = new Set(expandedToolGroups.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedToolGroups.value = next
}

const feedEntries = useMemoryFeedEntries(toRef(props, 'messages'))

function shouldRenderMarkdownForRole(role: string) {
  const roleKey = normalizeMemoryRole(role)
  return roleKey !== 'user'
}

function renderFeedMarkdown(text: string) {
  const raw = String(text || '')
  if (!raw) return ''
  try {
    return renderMarkdownText(raw)
  } catch {
    return `<pre>${escapeHtml(raw)}</pre>`
  }
}

function textForMessage(message: MessageEnvelope) {
  return extractMemoryMessageText(message)
}

</script>

<template>
  <template v-if="feedEntries.length > 0">
    <template v-for="entry in feedEntries" :key="entry.key">
      <div
        v-if="entry.type === 'message'"
        class="feed-item"
        :class="`role-${feedRoleClass(String((entry.message as any)?.role || 'assistant'))}`"
      >
        <div class="feed-head">
          <span class="feed-role">{{ memoryRoleLabel(feedRoleClass(String((entry.message as any)?.role || 'assistant')), String((entry.message as any)?.role || '')) }}</span>
          <span class="feed-time">{{ String((entry.message as any)?.created_at || '') }}</span>
        </div>
        <div class="feed-parts">
          <template v-for="(part, idx) in messageParts(entry.message)" :key="`${entry.key}-${idx}`">
            <div
              v-if="String((part as any)?.type || '') === 'text' && markdownPreview && shouldRenderMarkdownForRole(String((entry.message as any)?.role || 'assistant'))"
              class="feed-text markdown-part"
              v-html="renderFeedMarkdown(String((part as any)?.text || ''))"
            ></div>
            <div v-else-if="String((part as any)?.type || '') === 'text'" class="feed-text">{{ String((part as any)?.text || '') }}</div>
            <MemoryResourcePart v-else-if="String((part as any)?.type || '') === 'resource'" :part="part as Record<string, unknown>" />
            <MemoryToolCallPart v-else-if="String((part as any)?.type || '') === 'tool_call'" :part="part as Record<string, unknown>" />
            <pre v-else class="feed-structured">{{ JSON.stringify(part, null, 2) }}</pre>
          </template>
          <MemoryMessageActions
            v-if="textForMessage(entry.message)"
            class="feed-actions"
            @save="emit('saveMessage', textForMessage(entry.message))"
            @copy="emit('copyMessage', textForMessage(entry.message))"
          />
        </div>
      </div>
      <div
        v-else
        class="feed-item role-tool tool-group"
        :class="{ expanded: isToolGroupExpanded(entry.key) }"
      >
        <button class="tool-group-head" type="button" @click="toggleToolGroup(entry.key)">
          <span class="tool-group-main-row">
            <span class="tool-group-left">
              <span class="tool-group-caret">{{ isToolGroupExpanded(entry.key) ? 'v' : '>' }}</span>
              <span class="feed-role">Tool</span>
              <span class="tool-group-count">{{ toolGroupLabel(entry) }}</span>
            </span>
            <span class="feed-time">{{ toolGroupTime(entry) }}</span>
          </span>
          <span v-if="lastToolInstruction(entry)" class="tool-group-instruction">{{ lastToolInstruction(entry) }}</span>
        </button>
        <div v-if="isToolGroupExpanded(entry.key)" class="tool-group-list">
          <div
            v-for="(part, idx) in toolGroupParts(entry)"
            :key="`${entry.key}-${String(part.call_id || idx)}`"
            class="tool-group-row"
          >
            <div class="tool-group-row-head">
              <span class="tool-group-dot" :class="`status-${toolStatus(part)}`"></span>
              <span class="tool-group-name">{{ toolName(part) }}</span>
              <span v-if="toolDuration(part)" class="tool-group-duration">{{ toolDuration(part) }}</span>
              <span class="tool-group-status">{{ toolStatus(part) }}</span>
            </div>
            <MemoryToolCallPart :part="part" />
          </div>
        </div>
      </div>
    </template>
  </template>
</template>

<style scoped>
.feed-item {
  flex: 0 0 auto;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
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

.feed-actions {
  align-self: flex-end;
  margin-top: 2px;
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

.tool-group-head {
  width: 100%;
  border: 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(0, 0, 0, 0.2);
  color: inherit;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
  cursor: pointer;
  text-align: left;
}

.tool-group-head:hover {
  background: rgba(83, 22, 54, 0.22);
}

.tool-group-main-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.tool-group-left {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
}

.tool-group-caret {
  width: 12px;
  color: rgba(244, 114, 182, 0.95);
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
}

.tool-group-count,
.tool-group-instruction,
.tool-group-duration,
.tool-group-status {
  color: rgba(203, 213, 225, 0.78);
  font-size: 11px;
}

.tool-group-instruction {
  display: block;
  padding-left: 20px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.45;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
}

.tool-group-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
}

.tool-group-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tool-group-row + .tool-group-row {
  padding-top: 8px;
  border-top: 1px solid rgba(244, 114, 182, 0.16);
}

.tool-group-row-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.tool-group-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  flex: 0 0 auto;
  background: rgba(125, 211, 252, 0.95);
}

.tool-group-dot.status-completed {
  background: rgba(52, 211, 153, 0.95);
}

.tool-group-dot.status-error,
.tool-group-dot.status-failed,
.tool-group-dot.status-timeout {
  background: rgba(248, 113, 113, 0.95);
}

.tool-group-name {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(248, 250, 252, 0.95);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 12px;
}
</style>
