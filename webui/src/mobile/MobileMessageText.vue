<script setup lang="ts">
import { computed, ref } from 'vue'
import { openLocalFile, type MessageEnvelope, type MessagePart } from '../api'
import type { ParsedFilePatch } from '../utils/responseMetadataDiff'
import MemoryFileDiffDialog from '../components/MemoryFileDiffDialog.vue'
import ImageLightbox from '../components/ImageLightbox.vue'
import MemoryMetadataDisclosure from '../components/MemoryMetadataDisclosure.vue'
import MemoryResourcePart from '../components/MemoryResourcePart.vue'
import MemoryResponseMetadataPart from '../components/MemoryResponseMetadataPart.vue'
import MemoryToolCallPart from '../components/MemoryToolCallPart.vue'
import { handleMarkdownCodeCopyClick } from '../components/markdownCodeCopy'
import {
  collectMessageFilePatches,
  localFileLinkFromAnchor,
  matchingFilePatches,
} from '../components/memoryFileLinks'
import {
  isResponseMetadataPart,
  memoryMessageDisplayParts,
  responseMetadataPartData,
} from '../components/memoryFeedTools'
import { renderMessageMarkdown, shouldRenderMarkdown } from './mobileMessageRender'

const props = defineProps<{
  message: MessageEnvelope
}>()

function isTextPart(part: MessagePart) {
  return String((part as any)?.type || '') === 'text'
}

function isResourcePart(part: MessagePart) {
  return String((part as any)?.type || '') === 'resource'
}

function isToolCallPart(part: MessagePart) {
  return String((part as any)?.type || '') === 'tool_call'
}

function partText(part: MessagePart) {
  return String((part as any)?.text || '')
}

const displayParts = computed(() => memoryMessageDisplayParts(props.message))
const filePatches = computed(() => collectMessageFilePatches(props.message))
const selectedDiffPath = ref('')
const selectedDiffPatches = ref<ParsedFilePatch[]>([])
const previewImage = ref({ src: '', alt: '' })

async function handleMarkdownClick(event: MouseEvent) {
  await handleMarkdownCodeCopyClick(event)
  if (event.defaultPrevented) return
  const image = (event.target as HTMLElement | null)?.closest('img') as HTMLImageElement | null
  if (image) {
    previewImage.value = { src: image.currentSrc || image.src, alt: image.alt }
    return
  }
  const anchor = (event.target as HTMLElement | null)?.closest('a') as HTMLAnchorElement | null
  if (!anchor) return
  const file = localFileLinkFromAnchor(anchor)
  if (!file) return

  event.preventDefault()
  const patches = matchingFilePatches(file.path, filePatches.value)
  if (patches.length) {
    selectedDiffPath.value = file.path
    selectedDiffPatches.value = patches
    return
  }
  try {
    await openLocalFile(file.path)
  } catch (error) {
    window.alert(`Failed to open local file:\n${String((error as Error)?.message || error)}`)
  }
}

function closeFileDiff() {
  selectedDiffPath.value = ''
  selectedDiffPatches.value = []
}
</script>

<template>
  <div class="bubble-parts">
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
          v-if="isTextPart(entry.part as MessagePart) && partText(entry.part as MessagePart).trim().length > 0 && shouldRenderMarkdown(message)"
          class="bubble-text bubble-markdown"
          v-html="renderMessageMarkdown({ ...message, parts: [entry.part as MessagePart] })"
          @click="handleMarkdownClick"
        ></div>
        <div v-else-if="isTextPart(entry.part as MessagePart) && partText(entry.part as MessagePart).trim().length > 0" class="bubble-text">{{ partText(entry.part as MessagePart) }}</div>
        <div v-else-if="isTextPart(entry.part as MessagePart)" class="bubble-empty">[empty message]</div>
        <MemoryResourcePart v-else-if="isResourcePart(entry.part as MessagePart)" class="mobile-resource-part" :part="entry.part as Record<string, unknown>" />
        <MemoryToolCallPart v-else-if="isToolCallPart(entry.part as MessagePart)" class="mobile-tool-call-part" :part="entry.part as Record<string, unknown>" />
        <MemoryResponseMetadataPart
          v-else-if="isResponseMetadataPart(entry.part)"
          :data="responseMetadataPartData(entry.part)"
        />
        <pre v-else class="bubble-structured">{{ JSON.stringify(entry.part, null, 2) }}</pre>
      </template>
    </template>
    <div v-if="displayParts.length === 0" class="bubble-empty">
      [empty message]
    </div>
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
.bubble-parts {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.bubble-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.5;
  font-size: 14px;
}

.bubble-markdown {
  white-space: normal;
}

:deep(.bubble-markdown p) {
  margin: 0 0 8px 0;
}

:deep(.bubble-markdown p:last-child) {
  margin-bottom: 0;
}

:deep(.bubble-markdown pre) {
  max-width: 100%;
  margin: 8px 0;
  padding: 10px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.28);
  overflow: auto;
}

:deep(.bubble-markdown code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
}

:deep(.bubble-markdown ul),
:deep(.bubble-markdown ol) {
  margin: 6px 0 6px 18px;
  padding: 0;
}

:deep(.bubble-markdown li) {
  margin: 2px 0;
}

:deep(.bubble-markdown a) {
  color: rgba(125, 211, 252, 0.96);
  cursor: pointer;
}

:deep(.bubble-markdown img) {
  display: block;
  width: auto;
  max-width: min(240px, 100%);
  max-height: 180px;
  height: auto;
  margin: 8px 0;
  border-radius: 8px;
  object-fit: contain;
  cursor: zoom-in;
}

:deep(.bubble-markdown .katex-display) {
  max-width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
}

.bubble-structured {
  max-width: 100%;
  margin: 0;
  padding: 8px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.24);
  overflow: auto;
  white-space: pre-wrap;
  font-size: 12px;
}

.bubble-empty {
  color: rgba(242, 247, 255, 0.58);
  font-size: 13px;
  line-height: 1.5;
}

:deep(.mobile-resource-part .feed-resource-image),
:deep(.mobile-resource-part .feed-resource-video) {
  max-width: 100%;
}

:deep(.mobile-resource-part .feed-resource-uri) {
  display: none;
}

:deep(.mobile-tool-call-part) {
  width: 100%;
  min-width: 0;
  max-width: 100%;
}
</style>
