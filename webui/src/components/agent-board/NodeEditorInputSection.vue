<script setup lang="ts">
import type { NodeEditorAttachment } from '../../composables/useGlobalState'

defineProps<{
  attachments: NodeEditorAttachment[]
  inputText: string
  canSend: boolean
  isUploadingFiles: boolean
  goalActive: boolean
  goalEnabled: boolean
  goalTitle?: string
}>()

const emit = defineEmits<{
  'update:inputText': [value: string]
  'drop-input': [event: DragEvent]
  'paste-input': [event: ClipboardEvent]
  'remove-attachment': [index: number]
  'clear-attachments': []
  'toggle-goal': []
  send: []
}>()

function onInputKeyDown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  emit('send')
}

function attachmentExtension(file: NodeEditorAttachment) {
  const value = String(file.path || file.name || '').split('?')[0]?.split('#')[0] || ''
  const idx = value.lastIndexOf('.')
  if (idx < 0 || idx === value.length - 1) return ''
  return value.slice(idx + 1).toLowerCase()
}

function isImageAttachment(file: NodeEditorAttachment) {
  return ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'svg'].includes(attachmentExtension(file))
}

function normalizeAttachmentUrlPath(value: string) {
  const normalized = String(value || '').replace(/\\/g, '/')
  const lower = normalized.toLowerCase()
  if (lower.startsWith('/memories/')) return normalized
  if (lower.startsWith('memories/')) return `/${normalized}`
  if (lower.startsWith('./memories/')) return `/${normalized.slice(2)}`
  const marker = '/memories/'
  const markerIdx = lower.indexOf(marker)
  if (markerIdx >= 0) {
    return normalized.slice(markerIdx)
  }
  return ''
}

function isWebUrl(value: string) {
  return /^(https?|ftp):\/\//i.test(String(value || '').trim())
}

function isSpecialInlineUrl(value: string) {
  const text = String(value || '').trim().toLowerCase()
  return text.startsWith('data:') || text.startsWith('blob:')
}

function attachmentPreviewHref(file: NodeEditorAttachment) {
  const raw = String(file.path || '').trim()
  if (!raw) return ''
  if (isSpecialInlineUrl(raw) || isWebUrl(raw)) return raw
  if (raw.startsWith('/api/files/raw')) return raw
  const staticPath = normalizeAttachmentUrlPath(raw)
  if (staticPath) return staticPath
  return `/api/files/raw?path=${encodeURIComponent(raw)}`
}
</script>

<template>
  <section class="editor-section input-section" @drop.prevent="emit('drop-input', $event)">
    <div v-if="attachments.length > 0" class="attachment-list">
      <div
        v-for="(file, index) in attachments"
        :key="file.path"
        class="attachment-chip"
        :class="{ 'attachment-chip-image': isImageAttachment(file) }"
      >
        <a
          v-if="isImageAttachment(file) && attachmentPreviewHref(file)"
          class="attachment-thumb-link"
          :href="attachmentPreviewHref(file)"
          target="_blank"
          rel="noreferrer"
          :title="file.path"
        >
          <img class="attachment-thumb" :src="attachmentPreviewHref(file)" :alt="file.name" loading="lazy" />
        </a>
        <span v-if="!isImageAttachment(file)" class="attachment-name" :title="file.path">{{ file.name }}</span>
        <button class="attachment-remove" type="button" @click="emit('remove-attachment', index)">x</button>
      </div>
      <button class="attachment-clear" type="button" @click="emit('clear-attachments')">Clear</button>
    </div>

    <textarea
      class="input-box"
      rows="2"
      placeholder="Type input for this node, or drop files here."
      :value="inputText"
      @input="emit('update:inputText', ($event.target as HTMLTextAreaElement).value)"
      @keydown="onInputKeyDown"
      @paste="emit('paste-input', $event)"
    ></textarea>

    <div class="input-actions">
      <div v-if="isUploadingFiles" class="section-hint">Uploading files...</div>
      <div class="send-actions">
        <button
          class="goal-btn"
          :class="{ active: goalActive }"
          type="button"
          :title="goalTitle || (goalActive ? 'Disable goal mode' : 'Enable goal mode')"
          :disabled="!goalEnabled"
          @click="emit('toggle-goal')"
        >
          Goal
        </button>
        <button class="primary-btn" :disabled="!canSend" @click="emit('send')">
          Send
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.editor-section {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 8px;
  min-height: 0;
  width: 100%;
}

.input-section {
  flex: 1 1 auto;
}

.input-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.section-hint {
  font-size: 12px;
  color: var(--theme-panel-node-side-editor-text-secondary, rgba(148, 163, 184, 0.84));
}

.attachment-list {
  grid-column: 1 / -1;
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

.attachment-chip-image {
  border-radius: 14px;
  padding: 5px 9px 5px 5px;
}

.attachment-thumb-link {
  display: inline-flex;
  width: 52px;
  height: 42px;
  flex: 0 0 auto;
  overflow: hidden;
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.34);
  background-color: rgba(248, 250, 252, 0.12);
  background-image:
    linear-gradient(45deg, rgba(148, 163, 184, 0.22) 25%, transparent 25%),
    linear-gradient(-45deg, rgba(148, 163, 184, 0.22) 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, rgba(148, 163, 184, 0.22) 75%),
    linear-gradient(-45deg, transparent 75%, rgba(148, 163, 184, 0.22) 75%);
  background-position: 0 0, 0 6px, 6px -6px, -6px 0;
  background-size: 12px 12px;
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.26);
}

.attachment-thumb {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
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
.goal-btn,
.primary-btn {
  border: 1px solid var(--theme-panel-node-side-editor-button-border, rgba(148, 163, 184, 0.22));
  border-radius: 10px;
  background: var(--theme-panel-node-side-editor-button-background, rgba(15, 23, 42, 0.9));
  color: var(--theme-panel-node-side-editor-button-text, #f8fafc);
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
  min-height: 52px;
  max-height: 108px;
  resize: vertical;
  border: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.22));
  border-radius: 10px;
  background: var(--theme-panel-node-side-editor-input-background, rgba(15, 23, 42, 0.88));
  color: var(--theme-panel-node-side-editor-input-text, #f8fafc);
  padding: 10px 12px;
  outline: none;
}

.input-actions {
  min-height: 52px;
}

.send-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.goal-btn {
  width: 58px;
  min-height: 34px;
  background: rgba(15, 23, 42, 0.9);
  color: rgba(226, 232, 240, 0.86);
}

.goal-btn.active {
  border-color: rgba(34, 197, 94, 0.5);
  background: rgba(22, 101, 52, 0.3);
  color: #dcfce7;
}

.goal-btn:disabled {
  cursor: not-allowed;
  opacity: 0.46;
}

.primary-btn {
  background: rgba(59, 130, 246, 0.22);
  border-color: rgba(96, 165, 250, 0.42);
  pointer-events: auto;
}

@media (max-width: 760px) {
  .editor-section {
    grid-template-columns: minmax(0, 1fr);
  }

  .input-actions {
    min-height: 0;
    width: 100%;
  }
}
</style>
