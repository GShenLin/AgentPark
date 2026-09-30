<script setup lang="ts">
import { attachmentPreviewHref, isImageAttachment, type MessageAttachment, type MessageResource } from '../composables/messageAttachments'
import { computed } from 'vue'
const props = defineProps<{ resources: MessageResource[] }>()
const files = computed<MessageAttachment[]>(() => props.resources.map(resource => ({
  path: resource.uri, name: resource.name || resource.uri, kind: resource.kind, mime: resource.mime,
})))
</script>

<template>
  <div v-if="files.length" class="group-event-attachments">
    <a v-for="file in files" :key="file.path" :href="attachmentPreviewHref(file)" target="_blank" rel="noreferrer">
      <img v-if="isImageAttachment(file)" :src="attachmentPreviewHref(file)" :alt="file.name" loading="lazy" />
      <span>{{ file.name }}</span>
    </a>
  </div>
</template>

<style scoped>
.group-event-attachments { display: flex; flex-wrap: wrap; gap: 8px; }
a { display: flex; flex-direction: column; gap: 4px; padding: 8px; max-width: 190px; border: 1px solid var(--border-light); border-radius: 10px; }
img { width: 96px; height: 80px; object-fit: contain; }
span { overflow-wrap: anywhere; }
</style>
