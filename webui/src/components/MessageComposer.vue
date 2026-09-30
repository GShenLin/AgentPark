<script setup lang="ts">
import { ref } from 'vue'
import { attachmentPreviewHref, isImageAttachment, type MessageAttachment } from '../composables/messageAttachments'
import ActionButton from './ActionButton.vue'
import DangerButton from './DangerButton.vue'
import ExpandableTextarea from './ExpandableTextarea.vue'

const props = withDefaults(defineProps<{
  attachments: MessageAttachment[]
  inputText: string
  canSend: boolean
  isUploadingFiles: boolean
  goalActive?: boolean
  goalEnabled?: boolean
  goalTitle?: string
  audioInputEnabled?: boolean
  audioRecording?: boolean
  audioRecordingSupported?: boolean
  title?: string
  placeholder?: string
  sendLabel?: string
  disabled?: boolean
}>(), { title: 'Node input', placeholder: 'Type input for this node, or drop files here.', sendLabel: 'Send' })
const fileInput = ref<HTMLInputElement | null>(null)
function pickFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (files.length) emit('add-files', files)
}

const emit = defineEmits<{
  'add-files': [files: File[]]
  'update:inputText': [value: string]
  'drop-input': [event: DragEvent]
  'paste-input': [event: ClipboardEvent]
  'remove-attachment': [index: number]
  'toggle-goal': []
  'toggle-audio-recording': []
  send: []
}>()

function onInputKeyDown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  if (props.canSend && !props.isUploadingFiles && !props.disabled) emit('send')
}

function onInputDragOver(event: DragEvent) {
  event.preventDefault()
}

function onInputDrop(event: DragEvent) {
  event.preventDefault()
  event.stopPropagation()
  if (!props.disabled) emit('drop-input', event)
}

</script>

<template>
  <section class="editor-section input-section" @dragover.prevent @drop.prevent.stop="!disabled && emit('drop-input', $event)">
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
        <DangerButton
          class="attachment-remove"
          icon
          compact
          :disabled="disabled"
          :aria-label="`Remove ${file.name}`"
          title="Remove attachment"
          @click="emit('remove-attachment', index)"
        >
          <svg viewBox="0 0 12 12" aria-hidden="true">
            <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" />
          </svg>
        </DangerButton>
      </div>
    </div>

    <ExpandableTextarea
      :model-value="inputText"
      :title="title"
      :aria-label="title"
      :disabled="disabled"
      :rows="2"
      min-height="52px"
      :placeholder="placeholder"
      @update:model-value="emit('update:inputText', $event)"
      @keydown="onInputKeyDown"
      @paste="emit('paste-input', $event)"
      @dragover="onInputDragOver"
      @drop="onInputDrop"
    />

    <div class="input-actions">
      <div v-if="isUploadingFiles" class="section-hint">Uploading files...</div>
      <div class="send-actions">
        <input ref="fileInput" class="attachment-picker" type="file" multiple aria-label="添加附件" :disabled="disabled || isUploadingFiles" @change="pickFiles" />
        <ActionButton :disabled="disabled || isUploadingFiles" title="添加图片或文件" @click="fileInput?.click()">添加附件</ActionButton>
        <button
          v-if="goalEnabled"
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
          :disabled="disabled || !audioRecordingSupported || isUploadingFiles"
          :title="audioRecording ? 'Stop recording and attach audio' : 'Start microphone recording'"
          @click="emit('toggle-audio-recording')"
        >
          {{ audioRecording ? 'Stop audio' : 'Record audio' }}
        </button>
        <ActionButton variant="primary" :disabled="!canSend || isUploadingFiles || disabled" @click="emit('send')">
          {{ sendLabel }}
        </ActionButton>
      </div>
    </div>
  </section>
</template>


<style scoped src="./MessageComposer.css"></style>
