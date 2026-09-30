<script setup lang="ts">
import ConversationHeader from './ConversationHeader.vue'
import DangerButton from './DangerButton.vue'
import FormCheckbox from './FormCheckbox.vue'
import { t } from '../i18n'

defineProps<{
  memoryTitle: string
  memoryMeta: string | null
  memoryMode: 'agent' | 'file' | 'graph'
  isMarkdownPreview: boolean
  showLineNumbers: boolean
  isWordWrap: boolean
  isSaving: boolean
  graphStatus: string | null
  canClearMemory: boolean
  closable: boolean
}>()

const emit = defineEmits<{
  (event: 'update:isMarkdownPreview', value: boolean): void
  (event: 'update:showLineNumbers', value: boolean): void
  (event: 'update:isWordWrap', value: boolean): void
  (event: 'toggleFileMode'): void
  (event: 'clearMemory'): void
  (event: 'close'): void
}>()

</script>

<template>
  <ConversationHeader :title="memoryTitle || t('common.memory')" :subtitle="memoryMeta" :closable="closable" @close="emit('close')">
    <div class="mode-tabs">
      <DangerButton v-if="memoryMode === 'agent'" compact :disabled="!canClearMemory" @click="emit('clearMemory')">{{ t('memory.clear') }}</DangerButton>
      <button v-if="memoryMode !== 'graph'" class="mode-tab" :class="{ active: memoryMode === 'file' }" @click="emit('toggleFileMode')">{{ t('memory.fileMode') }}</button>
    </div>

    <div v-if="memoryMode !== 'graph'" class="view-controls">
      <label class="toggle-item">
        <FormCheckbox :model-value="isMarkdownPreview" @update:model-value="emit('update:isMarkdownPreview', $event)" />
        <span>{{ t('memory.markdown') }}</span>
      </label>
      <label class="toggle-item" :class="{ disabled: isMarkdownPreview }">
        <FormCheckbox
          :model-value="showLineNumbers"
          :disabled="isMarkdownPreview"
          @update:model-value="emit('update:showLineNumbers', $event)"
        />
        <span>{{ t('memory.lineNumbers') }}</span>
      </label>
      <label class="toggle-item">
        <FormCheckbox :model-value="isWordWrap" @update:model-value="emit('update:isWordWrap', $event)" />
        <span>{{ t('memory.wrap') }}</span>
      </label>
    </div>

    <div v-if="isSaving && memoryMode === 'file'" class="panel-status">{{ t('common.saving') }}</div>
    <div v-if="graphStatus && memoryMode === 'graph'" class="panel-status">{{ graphStatus }}</div>
  </ConversationHeader>
</template>

<style scoped>
.panel-status {
  font-size: var(--theme-panel-memory-panel-font-meta, 11px);
  color: rgba(56, 189, 248, 0.98);
}

.mode-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mode-tab {
  border: 1px solid var(--theme-panel-memory-panel-button-border, rgba(148, 163, 184, 0.3));
  background: var(--theme-panel-memory-panel-button-background, rgba(15, 23, 42, 0.7));
  color: var(--theme-panel-memory-panel-button-text, rgba(226, 232, 240, 0.94));
  border-radius: 8px;
  font-size: var(--theme-panel-memory-panel-font-small, 11px);
  padding: 4px 9px;
}

.mode-tab.active {
  border-color: var(--theme-panel-memory-panel-button-active-border, rgba(56, 189, 248, 0.65));
  background: var(--theme-panel-memory-panel-button-active-background, rgba(14, 116, 144, 0.28));
}

.mode-tab:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.view-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toggle-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--theme-panel-memory-panel-font-small, 11px);
  color: var(--theme-panel-memory-panel-text-secondary, rgba(226, 232, 240, 0.94));
  user-select: none;
}

.toggle-item.disabled {
  opacity: 0.45;
}

</style>
