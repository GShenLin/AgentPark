<script setup lang="ts">
import { ref, watch } from 'vue'
import type { LatestTurnProgressSummary, MessageEnvelope } from '../api'
import MemoryMetadataMessage from './MemoryMetadataMessage.vue'
import MemoryMessageActions from './MemoryMessageActions.vue'
import MemoryMessageParts from './MemoryMessageParts.vue'
import {
  feedRoleClass,
  memoryRoleLabel,
  toolGroupParts,
  toolGroupTime,
  type FeedProgressGroupEntry,
} from './memoryFeedTools'

const props = withDefaults(defineProps<{
  entry: FeedProgressGroupEntry
  markdownPreview: boolean
  compact?: boolean
  lazyLoad?: boolean
  loading?: boolean
  summary?: LatestTurnProgressSummary | null
}>(), {
  compact: false,
  lazyLoad: false,
  loading: false,
  summary: null,
})

const emit = defineEmits<{
  (event: 'save', text: string): void
  (event: 'copy', text: string): void
  (event: 'delete', messages: MessageEnvelope | MessageEnvelope[]): void
  (event: 'requestLoad'): void
}>()

const expanded = ref(false)
const openAfterLoad = ref(false)

watch(
  () => props.lazyLoad,
  (deferred) => {
    if (!deferred && openAfterLoad.value) {
      openAfterLoad.value = false
      expanded.value = true
    }
  },
)

function toggleProgress() {
  if (!expanded.value && props.lazyLoad) {
    if (props.loading) return
    openAfterLoad.value = true
    emit('requestLoad')
    return
  }
  expanded.value = !expanded.value
}

function deletableMessages() {
  return props.entry.messages.filter((message) => !!String((message as any)?.id || '').trim())
}

function groupLabel() {
  const deferredSummary = props.lazyLoad ? props.summary : null
  const messageCount = deferredSummary?.item_count ?? props.entry.messages.length
  const toolCount = deferredSummary?.tool_count ?? toolGroupParts(props.entry).length
  const pieces = [`${messageCount} ${messageCount === 1 ? 'item' : 'items'}`]
  if (toolCount > 0 || deferredSummary) pieces.push(`${toolCount} ${toolCount === 1 ? 'tool' : 'tools'}`)
  return pieces.join(' · ')
}
</script>

<template>
  <div class="progress-group" :class="{ expanded, compact }">
    <div class="progress-group-head">
      <button class="progress-group-toggle" type="button" :aria-expanded="expanded" @click="toggleProgress">
        <span class="progress-group-left">
          <span class="progress-group-caret">{{ expanded ? 'v' : '>' }}</span>
          <span class="progress-group-role">Progress</span>
          <span class="progress-group-count">{{ loading ? 'Loading…' : groupLabel() }}</span>
        </span>
        <span class="progress-group-time">{{ toolGroupTime(entry) }}</span>
      </button>
      <MemoryMessageActions
        v-if="deletableMessages().length > 0"
        class="progress-head-actions"
        :show-save="false"
        :show-copy="false"
        delete-title="删除整个 Progress"
        @delete="emit('delete', deletableMessages())"
      />
    </div>

    <div v-if="expanded" class="progress-group-list">
      <template v-for="(message, index) in entry.messages" :key="String((message as any)?.id || index)">
        <MemoryMetadataMessage
          v-if="feedRoleClass(String((message as any)?.role || '')) === 'metadata'"
          :message="message"
          :markdown-preview="markdownPreview"
          @save="emit('save', $event)"
          @copy="emit('copy', $event)"
          @delete="emit('delete', $event)"
        />
        <div
          v-else
          class="progress-message"
          :class="`role-${feedRoleClass(String((message as any)?.role || ''))}`"
        >
          <div class="progress-message-head">
            <span>{{ memoryRoleLabel(feedRoleClass(String((message as any)?.role || '')), String((message as any)?.role || '')) }}</span>
            <span>{{ String((message as any)?.created_at || '') }}</span>
          </div>
          <MemoryMessageParts
            :message="message"
            :markdown-preview="markdownPreview"
            @save="emit('save', $event)"
            @copy="emit('copy', $event)"
            @delete="emit('delete', $event)"
          />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.progress-group { flex: 0 0 auto; border: 1px solid rgba(56, 189, 248, 0.25); border-left: 4px solid rgba(56, 189, 248, 0.62); border-radius: 8px; background: rgba(14, 116, 144, 0.08); overflow: visible; }
.progress-group-head { position: sticky; top: 0; z-index: 20; width: 100%; border-radius: 7px; display: flex; align-items: center; color: inherit; background: rgba(8, 47, 73, 0.98); }
.progress-group.expanded .progress-group-head { border-radius: 7px 7px 0 0; border-bottom: 1px solid rgba(56, 189, 248, 0.2); box-shadow: 0 5px 10px rgba(2, 6, 23, 0.24); }
.progress-group-head:hover { background: rgba(12, 74, 110, 0.98); }
.progress-group-toggle { min-width: 0; flex: 1 1 auto; align-self: stretch; border: 0; padding: 9px 8px 9px 10px; display: flex; align-items: center; justify-content: space-between; gap: 10px; color: inherit; background: transparent; cursor: pointer; text-align: left; }
.progress-head-actions { flex: 0 0 auto; margin-right: 7px; }
.progress-group-left { display: inline-flex; align-items: center; min-width: 0; gap: 8px; }
.progress-group-caret { width: 12px; color: rgba(125, 211, 252, 0.96); font: 11px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.progress-group-role { font-size: 12px; font-weight: 700; }
.progress-group-count, .progress-group-time { color: rgba(203, 213, 225, 0.78); font-size: 11px; }
.progress-group-list { display: flex; flex-direction: column; gap: 8px; padding: 10px; }
.progress-message { border: 1px solid rgba(148, 163, 184, 0.18); border-radius: 7px; background: rgba(15, 23, 42, 0.45); overflow: visible; }
.progress-message-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 6px 9px; border-bottom: 1px solid rgba(148, 163, 184, 0.12); color: rgba(203, 213, 225, 0.82); font-size: 11px; }
.progress-message.role-tool { border-left: 3px solid rgba(244, 114, 182, 0.68); }
.progress-message.role-metadata { border-left: 3px solid rgba(167, 139, 250, 0.72); }
.progress-message.role-assistant, .progress-message.role-progress { border-left: 3px solid rgba(56, 189, 248, 0.62); }
.progress-group.compact { min-width: 0; }
.progress-group.compact .progress-group-head { align-items: stretch; }
.progress-group.compact .progress-group-toggle { gap: 8px; }
.progress-group.compact .progress-group-left { gap: 7px; }
.progress-group.compact .progress-group-count,
.progress-group.compact .progress-group-time { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; }
.progress-group.compact .progress-head-actions { align-self: center; }
.progress-group.compact .progress-group-list { gap: 8px; padding: 9px; }
</style>
