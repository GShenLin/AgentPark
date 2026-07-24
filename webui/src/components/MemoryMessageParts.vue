<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { openLocalFile, type MessageEnvelope } from '../api'
import type { ParsedFilePatch } from '../utils/responseMetadataDiff'
import MemoryFileDiffDialog from './MemoryFileDiffDialog.vue'
import MemoryMetadataDisclosure from './MemoryMetadataDisclosure.vue'
import MemoryMessageActions from './MemoryMessageActions.vue'
import ImageLightbox from './ImageLightbox.vue'
import MemoryResourcePart from './MemoryResourcePart.vue'
import MemoryResponseMetadataPart from './MemoryResponseMetadataPart.vue'
import MemoryToolCallPart from './MemoryToolCallPart.vue'
import { handleMarkdownCodeCopyClick } from './markdownCodeCopy'
import {
  collectMessageFilePatches,
  localFileLinkFromAnchor,
  matchingFilePatches,
} from './memoryFileLinks'
import { renderMarkdownText } from './memoryMarkdown'
import { extractMemoryMessageText } from './memoryMessageText'
import {
  isResponseMetadataPart,
  memoryMessageDisplayParts,
  normalizeMemoryRole,
  responseMetadataPartData,
} from './memoryFeedTools'

const props = withDefaults(defineProps<{
  message: MessageEnvelope
  markdownPreview: boolean
  showActions?: boolean
  metadataDisclosure?: boolean
  metadataDeferred?: boolean
  ensureMetadata?: () => Promise<void>
}>(), {
  showActions: true,
  metadataDisclosure: true,
  metadataDeferred: false,
})

const emit = defineEmits<{
  (event: 'save', text: string): void
  (event: 'copy', text: string): void
  (event: 'delete', message: MessageEnvelope | MessageEnvelope[]): void
}>()

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function shouldRenderMarkdown() {
  return normalizeMemoryRole(String((props.message as any)?.role || 'assistant')) !== 'user'
}

function renderFeedMarkdown(text: string) {
  let raw = String(text || '')
  if (!raw) return ''
  if (raw.startsWith('returncode:') && raw.includes('--- stdout ---')) {
    raw = '```text\n' + raw + '\n```'
  }
  try {
    return renderMarkdownText(raw)
  } catch {
    return `<pre>${escapeHtml(raw)}</pre>`
  }
}

function isAssistantProgressMeta(part: unknown) {
  return !!(part && typeof part === 'object' && String((part as any).type || '') === 'meta' && String((part as any)?.meta?.kind || '') === 'assistant_progress')
}

function messageText() {
  return extractMemoryMessageText(props.message)
}

function canDelete() {
  return !!String((props.message as any)?.id || '').trim()
}

function deletableMessages() {
  const associated = (props.message as any)?.__associatedMetadataMessages
  return Array.isArray(associated) && associated.length > 0 ? [props.message, ...associated] : props.message
}

const displayParts = computed(() => memoryMessageDisplayParts(props.message, props.metadataDisclosure))
const filePatches = computed(() => collectMessageFilePatches(props.message))
const selectedDiffPath = ref('')
const selectedDiffPatches = ref<ParsedFilePatch[]>([])
const previewImage = ref({ src: '', alt: '' })
const resolvingFilePath = ref('')

function showFileDiff(path: string, patches: ParsedFilePatch[]) {
  selectedDiffPath.value = path
  selectedDiffPatches.value = patches
}

async function openFileWithoutDiff(path: string) {
  try {
    await openLocalFile(path)
  } catch (error) {
    window.alert(`Failed to open local file:\n${String((error as Error)?.message || error)}`)
  }
}

async function resolveFileLink(path: string) {
  let patches = matchingFilePatches(path, filePatches.value)
  if (patches.length) {
    showFileDiff(path, patches)
    return
  }

  if (props.metadataDeferred) {
    if (!props.ensureMetadata) {
      window.alert('File change metadata is not available yet.')
      return
    }
    if (resolvingFilePath.value) return
    resolvingFilePath.value = path
    try {
      await props.ensureMetadata()
      await nextTick()
      if (resolvingFilePath.value !== path) return
      if (props.metadataDeferred) {
        window.alert('Failed to load file change metadata. Please try again.')
        return
      }
      patches = matchingFilePatches(path, filePatches.value)
      if (patches.length) {
        showFileDiff(path, patches)
        return
      }
    } finally {
      if (resolvingFilePath.value === path) resolvingFilePath.value = ''
    }
  }

  await openFileWithoutDiff(path)
}

async function handleMarkdownClick(event: MouseEvent) {
  await handleMarkdownCodeCopyClick(event)
  if (event.defaultPrevented) return

  const target = event.target as HTMLElement | null
  const image = target?.closest('img') as HTMLImageElement | null
  if (image) {
    previewImage.value = { src: image.currentSrc || image.src, alt: image.alt }
    return
  }
  const anchor = target?.closest('a') as HTMLAnchorElement | null
  if (!anchor) return
  const file = localFileLinkFromAnchor(anchor)
  if (!file) return

  event.preventDefault()
  await resolveFileLink(file.path)
}

function closeFileDiff() {
  selectedDiffPath.value = ''
  selectedDiffPatches.value = []
}
</script>

<template>
  <div class="feed-parts">
    <template v-for="entry in displayParts" :key="entry.key">
      <MemoryMetadataDisclosure
        v-if="entry.kind === 'associated_metadata'"
        :created-at="entry.createdAt"
        default-expanded
      >
        <MemoryResponseMetadataPart
          v-for="(part, index) in entry.parts"
          :key="index"
          :data="responseMetadataPartData(part)"
        />
      </MemoryMetadataDisclosure>
      <template v-else>
        <div
          v-if="String((entry.part as any)?.type || '') === 'text' && markdownPreview && shouldRenderMarkdown()"
          class="feed-text markdown-part"
          v-html="renderFeedMarkdown(String((entry.part as any)?.text || ''))"
          @click="handleMarkdownClick"
        ></div>
        <div v-else-if="String((entry.part as any)?.type || '') === 'text'" class="feed-text">{{ String((entry.part as any)?.text || '') }}</div>
        <MemoryResourcePart v-else-if="String((entry.part as any)?.type || '') === 'resource'" :part="entry.part as Record<string, unknown>" />
        <MemoryToolCallPart v-else-if="String((entry.part as any)?.type || '') === 'tool_call'" :part="entry.part as Record<string, unknown>" />
        <MemoryResponseMetadataPart
          v-else-if="isResponseMetadataPart(entry.part)"
          :data="responseMetadataPartData(entry.part)"
        />
        <div v-else-if="isAssistantProgressMeta(entry.part)" class="progress-context-note">Excluded from model context</div>
        <pre v-else class="feed-structured">{{ JSON.stringify(entry.part, null, 2) }}</pre>
      </template>
    </template>
    <MemoryMessageActions
      v-if="showActions && (messageText() || canDelete())"
      class="feed-actions"
      :show-save="!!messageText()"
      :show-copy="!!messageText()"
      :show-delete="canDelete()"
      @save="emit('save', messageText())"
      @copy="emit('copy', messageText())"
      @delete="emit('delete', deletableMessages())"
    />
    <MemoryFileDiffDialog
      :open="selectedDiffPatches.length > 0"
      :path="selectedDiffPath"
      :patches="selectedDiffPatches"
      @close="closeFileDiff"
    />
    <ImageLightbox
      :open="!!previewImage.src"
      :src="previewImage.src"
      :alt="previewImage.alt"
      @close="previewImage = { src: '', alt: '' }"
    />
  </div>
</template>

<style scoped>
.feed-parts { padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.feed-actions { align-self: flex-end; margin-top: 2px; }
.feed-text { white-space: pre-wrap; word-break: break-word; line-height: 1.55; }
.feed-text.markdown-part { white-space: normal; }
.progress-context-note { align-self: flex-start; padding: 2px 7px; border-radius: 999px; color: rgba(125, 211, 252, 0.9); background: rgba(14, 116, 144, 0.16); font-size: var(--theme-panel-memory-panel-font-small, 11px); }
.feed-structured { margin: 0; padding: 8px; border-radius: 8px; background: rgba(0, 0, 0, 0.24); overflow: auto; font-size: var(--theme-panel-memory-panel-font-ui, 12px); }
:deep(.feed-text.markdown-part p) { margin: 0 0 8px 0; }
:deep(.feed-text.markdown-part p:last-child) { margin-bottom: 0; }
:deep(.feed-text.markdown-part pre) { margin: 8px 0; padding: 10px; border-radius: 8px; background: rgba(0, 0, 0, 0.28); overflow: auto; }
:deep(.feed-text.markdown-part .markdown-code-block pre) { margin: 0; padding: 10px 48px 34px 10px; background: transparent; }
:deep(.feed-text.markdown-part code) { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace; }
:deep(.feed-text.markdown-part ul), :deep(.feed-text.markdown-part ol) { margin: 6px 0 6px 18px; padding: 0; }
:deep(.feed-text.markdown-part li) { margin: 2px 0; }
:deep(.feed-text.markdown-part a) { color: rgba(125, 211, 252, 0.96); cursor: pointer; }
:deep(.feed-text.markdown-part img) { display: block; width: auto; max-width: min(240px, 100%); max-height: 180px; height: auto; margin: 8px 0; border-radius: 8px; object-fit: contain; cursor: zoom-in; }
</style>
