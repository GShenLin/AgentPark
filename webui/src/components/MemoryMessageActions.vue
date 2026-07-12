<script setup lang="ts">
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
    <button
      v-if="showSave"
      class="message-action-btn"
      type="button"
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
    </button>
    <button
      v-if="showCopy"
      class="message-action-btn"
      type="button"
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
    </button>
    <button
      v-if="showDelete"
      class="message-action-btn danger"
      type="button"
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
    </button>
  </div>
</template>

<style scoped>
.message-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.message-action-btn {
  width: 28px;
  height: 28px;
  box-sizing: border-box;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 7px;
  padding: 0;
  background: rgba(15, 23, 42, 0.74);
  color: rgba(203, 213, 225, 0.94);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.message-action-btn:hover:not(:disabled) {
  border-color: rgba(125, 211, 252, 0.52);
  color: rgba(240, 249, 255, 0.98);
  background: rgba(8, 47, 73, 0.72);
}

.message-action-btn.danger {
  border-color: rgba(248, 113, 113, 0.32);
  color: rgba(252, 165, 165, 0.95);
}

.message-action-btn.danger:hover:not(:disabled) {
  border-color: rgba(248, 113, 113, 0.62);
  color: rgba(254, 226, 226, 0.98);
  background: rgba(127, 29, 29, 0.58);
}

.message-action-btn:disabled {
  opacity: 0.44;
  cursor: not-allowed;
}

.message-action-btn svg {
  display: block;
  flex: 0 0 auto;
}
</style>
