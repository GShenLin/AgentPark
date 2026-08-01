<script setup lang="ts">
import ActionButton from './ActionButton.vue'
import DangerButton from './DangerButton.vue'

withDefaults(defineProps<{
  disabled?: boolean
  showSave?: boolean
  showCopy?: boolean
  showDelete?: boolean
  deleteTitle?: string
}>(), {
  disabled: false,
  showSave: true,
  showCopy: true,
  showDelete: true,
  deleteTitle: '删除这条对话',
})

const emit = defineEmits<{
  (event: 'save'): void
  (event: 'copy'): void
  (event: 'delete'): void
}>()
</script>

<template>
  <div class="message-actions">
    <ActionButton
      v-if="showSave"
      icon
      compact
      title="保存为 Markdown"
      aria-label="保存为 Markdown"
      :disabled="disabled"
      @click.stop="emit('save')"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path
          fill="currentColor"
          d="M5 3h12.2L21 6.8V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm2 2v6h9V5H7Zm1 11v3h8v-3H8Zm7-11v4h1V5h-1Z"
        />
      </svg>
    </ActionButton>
    <ActionButton
      v-if="showCopy"
      icon
      compact
      title="Copy text"
      aria-label="Copy text"
      :disabled="disabled"
      @click.stop="emit('copy')"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path
          fill="currentColor"
          d="M8 7a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-8a2 2 0 0 1-2-2V7Zm2 0v11h8V7h-8ZM4 3h9v2H5v10H3V4a1 1 0 0 1 1-1Z"
        />
      </svg>
    </ActionButton>
    <DangerButton
      v-if="showDelete"
      icon
      compact
      :title="deleteTitle"
      :aria-label="deleteTitle"
      :disabled="disabled"
      @click.stop="emit('delete')"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path
          fill="currentColor"
          d="M9 3h6l1 2h4v2H4V5h4l1-2Zm1 6h2v9h-2V9Zm4 0h2v9h-2V9ZM7 9h2v9h8V9h2v10a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V9Z"
        />
      </svg>
    </DangerButton>
  </div>
</template>

<style scoped>
.message-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.message-actions svg {
  display: block;
  flex: 0 0 auto;
}
</style>
