<script setup lang="ts">
import type { MessageEnvelope, MessagePart } from '../api'
import MemoryResourcePart from '../components/MemoryResourcePart.vue'
import MemoryToolCallPart from '../components/MemoryToolCallPart.vue'
import { renderMessageMarkdown, shouldRenderMarkdown } from './mobileMessageRender'

defineProps<{
  message: MessageEnvelope
}>()

function messageParts(message: MessageEnvelope) {
  return Array.isArray(message.parts) ? message.parts : []
}

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
</script>

<template>
  <div class="bubble-parts">
    <template v-for="(part, index) in messageParts(message)" :key="`${String(part.type || 'part')}-${index}`">
      <div
        v-if="isTextPart(part) && partText(part).trim().length > 0 && shouldRenderMarkdown(message)"
        class="bubble-text bubble-markdown"
        v-html="renderMessageMarkdown({ ...message, parts: [part] })"
      ></div>
      <div v-else-if="isTextPart(part) && partText(part).trim().length > 0" class="bubble-text">{{ partText(part) }}</div>
      <div v-else-if="isTextPart(part)" class="bubble-empty">[empty message]</div>
      <MemoryResourcePart v-else-if="isResourcePart(part)" class="mobile-resource-part" :part="part as Record<string, unknown>" />
      <MemoryToolCallPart v-else-if="isToolCallPart(part)" class="mobile-tool-call-part" :part="part as Record<string, unknown>" />
      <pre v-else class="bubble-structured">{{ JSON.stringify(part, null, 2) }}</pre>
    </template>
    <div v-if="messageParts(message).length === 0" class="bubble-empty">
      [empty message]
    </div>
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
