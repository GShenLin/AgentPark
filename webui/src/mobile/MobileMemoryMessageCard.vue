<script setup lang="ts">
import type { MessageEnvelope } from '../api'
import { extractMemoryMessageText } from '../components/memoryMessageText'
import { feedRoleClass, memoryRoleLabel } from '../components/memoryFeedTools'
import MobileMessageText from './MobileMessageText.vue'

const props = defineProps<{
  message: MessageEnvelope
}>()

const emit = defineEmits<{
  (event: 'save', text: string): void
  (event: 'copy', text: string): void
  (event: 'delete', message: MessageEnvelope): void
}>()

function roleKey() {
  return feedRoleClass(String((props.message as any)?.role || 'assistant'))
}

function roleLabel() {
  return memoryRoleLabel(roleKey(), String((props.message as any)?.role || ''))
}

function messageText() {
  return extractMemoryMessageText(props.message)
}

function canDelete() {
  return !!String((props.message as any)?.id || '').trim()
}
</script>

<template>
  <article class="mobile-memory-card" :class="`role-${roleKey()}`">
    <div class="mobile-memory-card-head">
      <span>{{ roleLabel() }}</span>
      <span>{{ String((message as any)?.created_at || '') }}</span>
    </div>
    <div class="mobile-memory-card-body">
      <MobileMessageText :message="message" />
      <div v-if="messageText() || canDelete()" class="mobile-memory-card-actions">
        <button v-if="messageText()" type="button" class="mobile-card-action save" @click="emit('save', messageText())">Save</button>
        <button v-if="messageText()" type="button" class="mobile-card-action copy" @click="emit('copy', messageText())">Copy</button>
        <button v-if="canDelete()" type="button" class="mobile-card-action delete" @click="emit('delete', message)">Delete</button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.mobile-memory-card {
  min-width: 0;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.58);
  overflow: visible;
}

.mobile-memory-card.role-user { border-left: 4px solid rgba(56, 189, 248, 0.68); }
.mobile-memory-card.role-assistant { border-left: 4px solid rgba(34, 197, 94, 0.68); }
.mobile-memory-card.role-progress { border-left: 4px solid rgba(56, 189, 248, 0.62); }
.mobile-memory-card.role-tool { border-left: 4px solid rgba(244, 114, 182, 0.68); }
.mobile-memory-card.role-metadata { border-left: 4px solid rgba(167, 139, 250, 0.72); background: rgba(76, 29, 149, 0.12); }

.mobile-memory-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 9px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  color: rgba(226, 232, 240, 0.94);
  font-size: 11px;
  font-weight: 700;
}

.mobile-memory-card-head span:last-child {
  min-width: 0;
  color: rgba(148, 163, 184, 0.88);
  font-size: 10px;
  font-weight: 400;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-memory-card-body { padding: 9px; }

.mobile-memory-card-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.mobile-card-action {
  min-height: 30px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: rgba(15, 23, 42, 0.74);
  color: rgba(226, 232, 240, 0.94);
  font-size: 12px;
}

.mobile-card-action.save { border-color: rgba(74, 222, 128, 0.4); color: rgba(187, 247, 208, 0.96); }
.mobile-card-action.copy { border-color: rgba(125, 211, 252, 0.4); color: rgba(186, 230, 253, 0.96); }
.mobile-card-action.delete { border-color: rgba(248, 113, 113, 0.45); color: rgba(254, 202, 202, 0.98); background: rgba(127, 29, 29, 0.28); }
</style>
