<script setup lang="ts">
import type { NodeEditorAttachment } from '../../composables/useGlobalState'
import ExpandableTextarea from '../ExpandableTextarea.vue'

defineProps<{
  attachments: NodeEditorAttachment[]
  inputText: string
  canSend: boolean
  isUploadingFiles: boolean
  goalActive: boolean
  goalEnabled: boolean
  goalTitle?: string
  audioInputEnabled: boolean
  audioRecording: boolean
  audioRecordingSupported: boolean
}>()

const emit = defineEmits<{
  'update:inputText': [value: string]
  'drop-input': [event: DragEvent]
  'paste-input': [event: ClipboardEvent]
  'remove-attachment': [index: number]
  'toggle-goal': []
  'toggle-audio-recording': []
  send: []
}>()

function onInputKeyDown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  emit('send')
}

function onInputDragOver(event: DragEvent) {
  event.preventDefault()
}

function onInputDrop(event: DragEvent) {
  event.preventDefault()
  event.stopPropagation()
  emit('drop-input', event)
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
        class="attachment-item"
        :class="isImageAttachment(file) ? 'attachment-item-image' : 'attachment-item-file'"
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
        <button
          class="attachment-remove"
          type="button"
          :aria-label="`Remove ${file.name}`"
          title="Remove attachment"
          @click="emit('remove-attachment', index)"
        >
          <svg viewBox="0 0 12 12" aria-hidden="true">
            <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" />
          </svg>
        </button>
      </div>
    </div>

    <ExpandableTextarea
      :model-value="inputText"
      title="Node Input"
      aria-label="Node input"
      :rows="2"
      min-height="52px"
      max-height="108px"
      placeholder="Type input for this node, or drop files here."
      @update:model-value="emit('update:inputText', $event)"
      @keydown="onInputKeyDown"
      @paste="emit('paste-input', $event)"
      @dragover="onInputDragOver"
      @drop="onInputDrop"
    />

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
        <button
          v-if="audioInputEnabled"
          class="record-btn"
          :class="{ active: audioRecording }"
          type="button"
          :disabled="!audioRecordingSupported || isUploadingFiles"
          :title="audioRecording ? 'Stop recording and attach audio' : 'Start microphone recording'"
          @click="emit('toggle-audio-recording')"
        >
          {{ audioRecording ? 'Stop audio' : 'Record audio' }}
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

.attachment-item {
  position: relative;
  flex: 0 0 auto;
}

.attachment-item-file {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  border-radius: 999px;
  border: 1px solid rgba(125, 211, 252, 0.26);
  background: rgba(14, 116, 144, 0.18);
  padding: 5px 10px;
}

.attachment-item-image {
  width: 80px;
  height: 80px;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.88);
  box-shadow: 0 3px 12px rgba(2, 6, 23, 0.28);
}

.attachment-thumb-link {
  display: block;
  width: 100%;
  height: 100%;
  overflow: hidden;
  border-radius: 13px;
  background: rgba(30, 41, 59, 0.92);
}

.attachment-thumb {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
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
.goal-btn,
.record-btn,
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
  display: grid;
  place-items: center;
  padding: 0;
  width: 20px;
  height: 20px;
  border-radius: 999px;
  background: rgba(2, 6, 23, 0.86);
  color: rgba(248, 250, 252, 0.96);
}

.attachment-item-image .attachment-remove {
  position: absolute;
  top: 5px;
  right: 5px;
  border-color: rgba(226, 232, 240, 0.28);
  box-shadow: 0 1px 5px rgba(0, 0, 0, 0.42);
}

.attachment-remove:hover {
  border-color: rgba(248, 250, 252, 0.56);
  background: rgba(15, 23, 42, 0.98);
}

.attachment-remove svg {
  display: block;
  width: 10px;
  height: 10px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-width: 1.7;
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

.record-btn.active {
  border-color: rgba(248, 113, 113, 0.72);
  background: rgba(153, 27, 27, 0.42);
  color: #fee2e2;
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
