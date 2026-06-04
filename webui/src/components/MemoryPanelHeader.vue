<script setup lang="ts">
defineProps<{
  memoryTitle: string
  memoryMeta: string | null
  memoryMode: 'agent' | 'file' | 'graph'
  isMarkdownPreview: boolean
  showLineNumbers: boolean
  isWordWrap: boolean
  memoryAutoScroll: boolean
  isSaving: boolean
  graphStatus: string | null
}>()

const emit = defineEmits<{
  (event: 'update:memoryMode', value: 'agent' | 'file' | 'graph'): void
  (event: 'update:isMarkdownPreview', value: boolean): void
  (event: 'update:showLineNumbers', value: boolean): void
  (event: 'update:isWordWrap', value: boolean): void
  (event: 'update:memoryAutoScroll', value: boolean): void
}>()

function readChecked(event: Event) {
  return Boolean((event.target as HTMLInputElement | null)?.checked)
}
</script>

<template>
  <div class="panel-head">
    <div class="panel-left">
      <div class="panel-title">{{ memoryTitle || 'Memory' }}</div>
      <div v-if="memoryMeta" class="panel-meta" :title="memoryMeta">{{ memoryMeta }}</div>
    </div>

    <div class="mode-tabs">
      <button class="mode-tab" :class="{ active: memoryMode === 'agent' }" @click="emit('update:memoryMode', 'agent')">Node</button>
      <button class="mode-tab" :class="{ active: memoryMode === 'file' }" @click="emit('update:memoryMode', 'file')">File</button>
      <button class="mode-tab" :class="{ active: memoryMode === 'graph' }" @click="emit('update:memoryMode', 'graph')">Graph</button>
    </div>

    <div v-if="memoryMode !== 'graph'" class="view-controls">
      <label class="toggle-item">
        <input type="checkbox" :checked="isMarkdownPreview" @change="emit('update:isMarkdownPreview', readChecked($event))" />
        <span>Markdown</span>
      </label>
      <label class="toggle-item" :class="{ disabled: isMarkdownPreview }">
        <input
          type="checkbox"
          :checked="showLineNumbers"
          :disabled="isMarkdownPreview"
          @change="emit('update:showLineNumbers', readChecked($event))"
        />
        <span>Line#</span>
      </label>
      <label class="toggle-item">
        <input type="checkbox" :checked="isWordWrap" @change="emit('update:isWordWrap', readChecked($event))" />
        <span>Wrap</span>
      </label>
      <label class="toggle-item">
        <input type="checkbox" :checked="memoryAutoScroll" @change="emit('update:memoryAutoScroll', readChecked($event))" />
        <span>AutoScroll</span>
      </label>
    </div>

    <div v-if="isSaving && memoryMode === 'file'" class="panel-status">Saving...</div>
    <div v-if="graphStatus && memoryMode === 'graph'" class="panel-status">{{ graphStatus }}</div>
  </div>
</template>

<style scoped>
.panel-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(2, 6, 23, 0.65);
}

.panel-left {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-right: auto;
}

.panel-title {
  font-size: 13px;
  font-weight: 700;
  color: rgba(248, 250, 252, 0.96);
}

.panel-meta {
  font-size: 11px;
  color: rgba(148, 163, 184, 0.92);
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-status {
  font-size: 11px;
  color: rgba(56, 189, 248, 0.98);
}

.mode-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mode-tab {
  border: 1px solid rgba(148, 163, 184, 0.3);
  background: rgba(15, 23, 42, 0.7);
  color: rgba(226, 232, 240, 0.94);
  border-radius: 8px;
  font-size: 11px;
  padding: 4px 9px;
}

.mode-tab.active {
  border-color: rgba(56, 189, 248, 0.65);
  background: rgba(14, 116, 144, 0.28);
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
  font-size: 11px;
  color: rgba(226, 232, 240, 0.94);
  user-select: none;
}

.toggle-item.disabled {
  opacity: 0.45;
}

@media (max-width: 1200px) {
  .panel-head {
    flex-wrap: wrap;
  }
}
</style>
