<script setup lang="ts">
import { toRef } from 'vue'
import type { LatestTurnProgressSummary, MessageEnvelope } from '../api'
import MemoryMessageParts from './MemoryMessageParts.vue'
import MemoryTurnGroup from './MemoryTurnGroup.vue'
import {
  feedRoleClass,
  memoryRoleLabel,
  useMemoryTurnEntries,
} from './memoryFeedTools'

const props = defineProps<{
  messages: MessageEnvelope[]
  markdownPreview: boolean
  historyComplete?: boolean
  progressLoaded?: boolean
  metadataLoaded?: boolean
  progressSummary?: LatestTurnProgressSummary | null
  loadingSection?: 'progress' | 'metadata' | null
  ensureLatestTurnMetadata?: () => Promise<void>
}>()

const emit = defineEmits<{
  (event: 'saveMessage', text: string): void
  (event: 'copyMessage', text: string): void
  (event: 'deleteMessage', target: MessageEnvelope | MessageEnvelope[] | { kind: 'turn'; userMessage: MessageEnvelope }): void
  (event: 'requestHistory'): void
  (event: 'requestSection', section: 'progress' | 'metadata'): void
}>()

const feedEntries = useMemoryTurnEntries(toRef(props, 'messages'))

function isLatestTurn(index: number) {
  for (let candidate = feedEntries.value.length - 1; candidate >= 0; candidate -= 1) {
    if (feedEntries.value[candidate]?.type === 'turn') return candidate === index
  }
  return false
}

function onTurnToggle(index: number, expanded: boolean) {
  if (!expanded && props.historyComplete === false && isLatestTurn(index)) emit('requestHistory')
}

function requestLatestTurnSection(index: number, section: 'progress' | 'metadata') {
  if (!isLatestTurn(index) || props.loadingSection) return
  emit('requestSection', section)
}

function sectionDeferred(index: number, section: 'progress' | 'metadata') {
  if (!isLatestTurn(index)) return false
  return section === 'progress' ? props.progressLoaded === false : props.metadataLoaded === false
}
</script>

<template>
  <template v-if="feedEntries.length > 0">
    <template v-for="(entry, index) in feedEntries" :key="entry.key">
      <div
        v-if="entry.type === 'message'"
        class="feed-item"
        :class="`role-${feedRoleClass(String((entry.message as any)?.role || 'assistant'))}`"
      >
        <div class="feed-head">
          <span class="feed-role">{{ memoryRoleLabel(feedRoleClass(String((entry.message as any)?.role || 'assistant')), String((entry.message as any)?.role || '')) }}</span>
          <span class="feed-time">{{ String((entry.message as any)?.created_at || '') }}</span>
        </div>
        <MemoryMessageParts
          :message="entry.message"
          :markdown-preview="markdownPreview"
          @save="emit('saveMessage', $event)"
          @copy="emit('copyMessage', $event)"
          @delete="emit('deleteMessage', $event)"
        />
      </div>
      <MemoryTurnGroup
        v-else
        :entry="entry"
        :markdown-preview="markdownPreview"
        :default-expanded="isLatestTurn(index)"
        :progress-deferred="sectionDeferred(index, 'progress')"
        :metadata-deferred="sectionDeferred(index, 'metadata')"
        :loading-section="isLatestTurn(index) ? loadingSection : null"
        :progress-summary="isLatestTurn(index) ? progressSummary : null"
        :ensure-metadata="isLatestTurn(index) ? ensureLatestTurnMetadata : undefined"
        @save="emit('saveMessage', $event)"
        @copy="emit('copyMessage', $event)"
        @delete="emit('deleteMessage', $event)"
        @toggle="onTurnToggle(index, $event)"
        @request-section="requestLatestTurnSection(index, $event)"
      />
    </template>
  </template>
</template>

<style scoped>
.feed-item { flex: 0 0 auto; border: 1px solid rgba(148, 163, 184, 0.22); border-radius: 8px; background: rgba(15, 23, 42, 0.45); overflow: visible; }
.feed-item.role-user { border-left: 4px solid rgba(56, 189, 248, 0.65); }
.feed-item.role-assistant { border-left: 4px solid rgba(34, 197, 94, 0.65); }
.feed-item.role-progress { border-left: 4px solid rgba(56, 189, 248, 0.62); background: rgba(14, 116, 144, 0.1); }
.feed-item.role-system { border-left: 4px solid rgba(148, 163, 184, 0.6); }
.feed-item.role-commentary { border-left: 4px solid rgba(250, 204, 21, 0.68); }
.feed-item.role-metadata { border-left: 4px solid rgba(167, 139, 250, 0.72); background: rgba(76, 29, 149, 0.12); }
.feed-item.role-tool { border-left: 4px solid rgba(244, 114, 182, 0.68); }
.feed-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 8px 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.14); border-radius: 7px 7px 0 0; background: rgba(0, 0, 0, 0.2); }
.feed-role { font-size: var(--theme-panel-memory-panel-font-ui, 12px); font-weight: 700; }
.feed-time { font-size: var(--theme-panel-memory-panel-font-meta, 11px); color: rgba(148, 163, 184, 0.9); }
</style>
