<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import type { ParsedFilePatch } from '../utils/responseMetadataDiff'
import DialogCloseButton from './DialogCloseButton.vue'
import ResponseFileDiff from './ResponseFileDiff.vue'

const props = defineProps<{
  open: boolean
  path: string
  patches: ParsedFilePatch[]
}>()

const emit = defineEmits<{
  (event: 'close'): void
}>()

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.open) emit('close')
}

watch(() => props.open, (open) => {
  if (open) window.addEventListener('keydown', handleKeydown)
  else window.removeEventListener('keydown', handleKeydown)
}, { immediate: true })

onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="diff-dialog-backdrop" @mousedown.self="emit('close')">
      <section class="diff-dialog" role="dialog" aria-modal="true" aria-label="File diff">
        <header class="diff-dialog-head">
          <div class="diff-dialog-title">
            <strong>File diff</strong>
            <span :title="path">{{ path }}</span>
          </div>
          <DialogCloseButton aria-label="Close file diff" @click="emit('close')" />
        </header>
        <div class="diff-dialog-body">
          <ResponseFileDiff :patches="patches" />
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.diff-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(2, 6, 23, 0.78);
}

.diff-dialog {
  display: flex;
  flex-direction: column;
  width: min(1400px, 96vw);
  max-height: 92vh;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 12px;
  background: #0b1220;
  color: rgba(226, 232, 240, 0.96);
  box-shadow: 0 28px 90px rgba(0, 0, 0, 0.5);
}

.diff-dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
}

.diff-dialog-title {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 3px;
}

.diff-dialog-title strong { font-size: 14px; }
.diff-dialog-title span {
  overflow: hidden;
  color: rgba(148, 163, 184, 0.94);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diff-dialog-body {
  min-height: 0;
  padding: 12px;
  overflow: auto;
}

@media (max-width: 700px) {
  .diff-dialog-backdrop { padding: 8px; }
  .diff-dialog { width: 100%; max-height: 96vh; }
}
</style>

