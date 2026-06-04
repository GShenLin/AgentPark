<script setup lang="ts">
import type { NodeEditorAttachment } from '../../composables/useGlobalState'

defineProps<{
  attachments: NodeEditorAttachment[]
  inputText: string
  canSend: boolean
  isSubmitting: boolean
  isUploadingFiles: boolean
}>()

const emit = defineEmits<{
  'update:inputText': [value: string]
  'drop-input': [event: DragEvent]
  'remove-attachment': [index: number]
  'clear-attachments': []
  send: []
}>()

function onInputKeyDown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  emit('send')
}
</script>

<template>
  <section class="editor-section input-section" @drop.prevent="emit('drop-input', $event)">
    <div class="section-head">
      <div class="section-title">Input</div>
    </div>

    <div v-if="attachments.length > 0" class="attachment-list">
      <div v-for="(file, index) in attachments" :key="file.path" class="attachment-chip">
        <span class="attachment-name" :title="file.path">{{ file.name }}</span>
        <button class="attachment-remove" type="button" @click="emit('remove-attachment', index)">x</button>
      </div>
      <button class="attachment-clear" type="button" @click="emit('clear-attachments')">Clear</button>
    </div>

    <textarea
      class="input-box"
      rows="4"
      placeholder="Type input for this node, or drop files here."
      :value="inputText"
      @input="emit('update:inputText', ($event.target as HTMLTextAreaElement).value)"
      @keydown="onInputKeyDown"
    ></textarea>

    <div class="input-actions">
      <div class="section-hint">{{ isUploadingFiles ? 'Uploading files...' : 'Ready to send to this node' }}</div>
      <button class="primary-btn" :disabled="!canSend" @click="emit('send')">
        {{ isSubmitting ? 'Sending...' : 'Send' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.editor-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}

.input-section {
  flex: 0 0 auto;
  padding-bottom: 2px;
}

.section-head,
.input-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: #e2e8f0;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.section-hint {
  font-size: 12px;
  color: rgba(148, 163, 184, 0.84);
}

.attachment-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.attachment-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  border-radius: 999px;
  border: 1px solid rgba(125, 211, 252, 0.26);
  background: rgba(14, 116, 144, 0.18);
  padding: 5px 10px;
}

.attachment-name {
  max-width: 210px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: #e0f2fe;
}

.attachment-remove,
.attachment-clear,
.primary-btn {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.9);
  color: #f8fafc;
  padding: 8px 12px;
  cursor: pointer;
  position: relative;
  z-index: 2;
}

.attachment-remove {
  padding: 0;
  width: 18px;
  height: 18px;
  border-radius: 999px;
}

.attachment-clear {
  padding: 6px 10px;
  font-size: 12px;
}

.input-box {
  width: 100%;
  min-height: 92px;
  resize: vertical;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.88);
  color: #f8fafc;
  padding: 10px 12px;
  outline: none;
}

.input-actions {
  margin-top: 2px;
}

.primary-btn {
  background: rgba(59, 130, 246, 0.22);
  border-color: rgba(96, 165, 250, 0.42);
  pointer-events: auto;
}
</style>
