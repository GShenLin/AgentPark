<script setup lang="ts">
import { toRef } from 'vue'
import type { LoadMemoryTurnDetails, MessageEnvelope } from '../api'
import MemoryMessageParts from './MemoryMessageParts.vue'
import MemoryTurnGroup from './MemoryTurnGroup.vue'
import { feedRoleClass, memoryRoleLabel, useMemoryTurnEntries } from './memoryFeedTools'

const props = defineProps<{
  messages: MessageEnvelope[]
  markdownPreview: boolean
  loadTurnDetails: LoadMemoryTurnDetails
}>()
const emit = defineEmits<{
  (event: 'saveMessage', text: string): void
  (event: 'copyMessage', text: string): void
  (event: 'deleteMessage', target: MessageEnvelope | MessageEnvelope[] | { kind: 'turn'; userMessage: MessageEnvelope }): void
}>()
const feedEntries = useMemoryTurnEntries(toRef(props, 'messages'))
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
        :load-turn-details="loadTurnDetails"
        :markdown-preview="markdownPreview"
        @save="emit('saveMessage', $event)"
        @copy="emit('copyMessage', $event)"
        @delete="emit('deleteMessage', $event)"
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
