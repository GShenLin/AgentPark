<script setup lang="ts">
import { ref } from 'vue'
import type { LatestTurnProgressSummary, MessageEnvelope } from '../api'
import MemoryMetadataMessage from './MemoryMetadataMessage.vue'
import MemoryMessageActions from './MemoryMessageActions.vue'
import MemoryMessageParts from './MemoryMessageParts.vue'
import MemoryProgressGroup from './MemoryProgressGroup.vue'
import { extractMemoryMessageText } from './memoryMessageText'
import {
  feedRoleClass,
  memoryRoleLabel,
  type FeedProgressGroupEntry,
  type FeedTurnEntry,
} from './memoryFeedTools'

const props = withDefaults(defineProps<{
  entry: FeedTurnEntry
  markdownPreview: boolean
  compact?: boolean
  defaultExpanded?: boolean
  progressDeferred?: boolean
  metadataDeferred?: boolean
  loadingSection?: 'progress' | 'metadata' | null
  progressSummary?: LatestTurnProgressSummary | null
  ensureMetadata?: () => Promise<void>
}>(), {
  compact: false,
  defaultExpanded: true,
  progressDeferred: false,
  metadataDeferred: false,
  loadingSection: null,
  progressSummary: null,
})

const emit = defineEmits<{
  (event: 'save', text: string): void
  (event: 'copy', text: string): void
  (event: 'delete', target: MessageEnvelope | MessageEnvelope[] | { kind: 'turn'; userMessage: MessageEnvelope }): void
  (event: 'toggle', expanded: boolean): void
  (event: 'requestSection', section: 'progress' | 'metadata'): void
}>()

const expanded = ref(props.defaultExpanded)

function toggleTurn() {
  expanded.value = !expanded.value
  emit('toggle', expanded.value)
}

function userSummary() {
  const text = extractMemoryMessageText(props.entry.userMessage).replace(/\s+/g, ' ').trim()
  if (!text) return 'User turn'
  const limit = props.compact ? 52 : 96
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

function turnTime() {
  const start = String((props.entry.userMessage as any)?.created_at || '')
  const lastMessage = props.entry.finalMessages[props.entry.finalMessages.length - 1] || props.entry.finalResponse
  const end = String((lastMessage as any)?.created_at || '')
  if (!end || start === end) return start
  return `${start} - ${end}`
}

function progressEntry(): FeedProgressGroupEntry {
  return {
    type: 'progress_group',
    key: `${props.entry.key}-progress`,
    messages: props.entry.progressMessages,
    startIndex: props.entry.startIndex + 1,
  }
}

function regularFinalMessages() {
  return props.entry.finalMessages.filter((message) => feedRoleClass(String((message as any)?.role || '')) !== 'metadata')
}

function finalMetadataMessages() {
  return props.entry.finalMessages.filter((message) => feedRoleClass(String((message as any)?.role || '')) === 'metadata')
}

function requestProgress() {
  emit('requestSection', 'progress')
}

function requestDeferredMetadata() {
  emit('requestSection', 'metadata')
}
</script>

<template>
  <section class="turn-group" :class="{ expanded, compact }">
    <div class="turn-head">
      <button class="turn-toggle" type="button" :aria-expanded="expanded" @click="toggleTurn">
        <span class="turn-head-main">
          <span class="turn-caret">{{ expanded ? 'v' : '>' }}</span>
          <span class="turn-label">Turn</span>
          <span class="turn-summary">{{ userSummary() }}</span>
        </span>
        <span class="turn-time">{{ turnTime() }}</span>
      </button>
      <MemoryMessageActions
        class="turn-actions"
        :show-save="false"
        :show-copy="false"
        delete-title="删除整个 Turn"
        @delete="emit('delete', { kind: 'turn', userMessage: entry.userMessage })"
      />
    </div>

    <div v-if="expanded" class="turn-content">
      <article class="turn-message role-user">
        <div class="turn-message-head">
          <span>User</span>
          <span>{{ String((entry.userMessage as any)?.created_at || '') }}</span>
        </div>
        <MemoryMessageParts
          :message="entry.userMessage"
          :markdown-preview="markdownPreview"
          :metadata-deferred="metadataDeferred"
          :ensure-metadata="ensureMetadata"
          @save="emit('save', $event)"
          @copy="emit('copy', $event)"
          @delete="emit('delete', $event)"
        />
      </article>

      <MemoryProgressGroup
        v-if="entry.progressMessages.length > 0 || progressDeferred"
        :entry="progressEntry()"
        :markdown-preview="markdownPreview"
        :compact="compact"
        :lazy-load="progressDeferred"
        :loading="loadingSection === 'progress'"
        :summary="progressSummary"
        @save="emit('save', $event)"
        @copy="emit('copy', $event)"
        @delete="emit('delete', $event)"
        @request-load="requestProgress"
      />

      <article
        v-if="entry.finalResponse"
        class="turn-message"
        :class="`role-${feedRoleClass(String((entry.finalResponse as any)?.role || ''))}`"
      >
        <div class="turn-message-head">
          <span>{{ memoryRoleLabel(feedRoleClass(String((entry.finalResponse as any)?.role || '')), String((entry.finalResponse as any)?.role || '')) }}</span>
          <span>{{ String((entry.finalResponse as any)?.created_at || '') }}</span>
        </div>
        <MemoryMessageParts
          :message="entry.finalResponse"
          :markdown-preview="markdownPreview"
          :metadata-deferred="metadataDeferred"
          :ensure-metadata="ensureMetadata"
          @save="emit('save', $event)"
          @copy="emit('copy', $event)"
          @delete="emit('delete', $event)"
        />
      </article>

      <div v-else class="turn-pending">Waiting for final response…</div>

      <article
        v-for="(message, index) in regularFinalMessages()"
        :key="String((message as any)?.id || `final-${index}`)"
        class="turn-message"
        :class="`role-${feedRoleClass(String((message as any)?.role || ''))}`"
      >
        <div class="turn-message-head">
          <span>{{ memoryRoleLabel(feedRoleClass(String((message as any)?.role || '')), String((message as any)?.role || '')) }}</span>
          <span>{{ String((message as any)?.created_at || '') }}</span>
        </div>
        <MemoryMessageParts
          :message="message"
          :markdown-preview="markdownPreview"
          :metadata-deferred="metadataDeferred"
          :ensure-metadata="ensureMetadata"
          @save="emit('save', $event)"
          @copy="emit('copy', $event)"
          @delete="emit('delete', $event)"
        />
      </article>

      <MemoryMetadataMessage
        v-for="(message, index) in finalMetadataMessages()"
        :key="String((message as any)?.id || `final-metadata-${index}`)"
        :message="message"
        :markdown-preview="markdownPreview"
        @save="emit('save', $event)"
        @copy="emit('copy', $event)"
        @delete="emit('delete', $event)"
      />
      <MemoryMetadataMessage
        v-if="metadataDeferred"
        :message="null"
        :markdown-preview="markdownPreview"
        deferred
        :loading="loadingSection === 'metadata'"
        @request-load="requestDeferredMetadata"
      />
    </div>
  </section>
</template>

<style scoped>
.turn-group { flex: 0 0 auto; border: 1px solid rgba(148, 163, 184, 0.28); border-radius: 10px; background: rgba(15, 23, 42, 0.34); overflow: visible; }
.turn-head { position: sticky; top: 0; z-index: 10; width: 100%; border-radius: 9px; display: flex; align-items: center; color: inherit; background: rgba(15, 23, 42, 0.98); }
.turn-group.expanded .turn-head { border-radius: 9px 9px 0 0; border-bottom: 1px solid rgba(148, 163, 184, 0.18); box-shadow: 0 5px 12px rgba(2, 6, 23, 0.28); }
.turn-head:hover { background: rgba(30, 41, 59, 0.98); }
.turn-toggle { min-width: 0; flex: 1 1 auto; align-self: stretch; border: 0; padding: 10px 8px 10px 12px; display: flex; align-items: center; justify-content: space-between; gap: 12px; color: inherit; background: transparent; cursor: pointer; text-align: left; }
.turn-actions { flex: 0 0 auto; margin-right: 8px; }
.turn-head-main { display: inline-flex; align-items: center; gap: 8px; min-width: 0; }
.turn-caret { width: 12px; flex: 0 0 auto; color: rgba(125, 211, 252, 0.96); font: 11px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.turn-label { flex: 0 0 auto; font-size: 12px; font-weight: 800; color: rgba(226, 232, 240, 0.98); }
.turn-summary { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: rgba(203, 213, 225, 0.8); font-size: 12px; }
.turn-time { flex: 0 0 auto; color: rgba(148, 163, 184, 0.9); font-size: 11px; }
.turn-content { display: flex; flex-direction: column; gap: 10px; padding: 10px; }
.turn-message { border: 1px solid rgba(148, 163, 184, 0.2); border-radius: 8px; background: rgba(15, 23, 42, 0.48); overflow: visible; }
.turn-message.role-user { border-left: 4px solid rgba(56, 189, 248, 0.65); }
.turn-message.role-assistant { border-left: 4px solid rgba(34, 197, 94, 0.65); }
.turn-message.role-system { border-left: 4px solid rgba(248, 113, 113, 0.72); }
.turn-message.role-metadata { border-left: 4px solid rgba(167, 139, 250, 0.72); background: rgba(76, 29, 149, 0.1); }
.turn-message.role-tool { border-left: 4px solid rgba(244, 114, 182, 0.68); }
.turn-message-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 7px 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.14); background: rgba(0, 0, 0, 0.18); color: rgba(226, 232, 240, 0.94); font-size: 12px; font-weight: 700; }
.turn-message-head span:last-child { color: rgba(148, 163, 184, 0.9); font-size: 11px; font-weight: 400; }
.turn-pending { padding: 9px 10px; border: 1px dashed rgba(148, 163, 184, 0.28); border-radius: 8px; color: rgba(148, 163, 184, 0.86); font-size: 12px; }
.turn-group.compact { min-width: 0; }
.turn-group.compact .turn-head { align-items: stretch; }
.turn-group.compact .turn-toggle { padding: 10px 8px 10px 10px; flex-direction: column; align-items: stretch; justify-content: center; gap: 4px; }
.turn-group.compact .turn-head-main { gap: 7px; }
.turn-group.compact .turn-summary { font-size: 11px; }
.turn-group.compact .turn-time { min-width: 0; padding-left: 19px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; }
.turn-group.compact .turn-actions { align-self: center; margin-right: 7px; }
.turn-group.compact .turn-content { gap: 9px; padding: 9px; }
.turn-group.compact .turn-message-head { font-size: 11px; }
</style>
