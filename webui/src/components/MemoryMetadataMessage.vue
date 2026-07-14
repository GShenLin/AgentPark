<script setup lang="ts">
import type { MessageEnvelope } from '../api'
import MemoryMetadataDisclosure from './MemoryMetadataDisclosure.vue'
import MemoryMessageParts from './MemoryMessageParts.vue'

const props = withDefaults(defineProps<{
  message?: MessageEnvelope | null
  markdownPreview: boolean
  deferred?: boolean
  loading?: boolean
}>(), {
  message: null,
  deferred: false,
  loading: false,
})

const emit = defineEmits<{
  (event: 'save', text: string): void
  (event: 'copy', text: string): void
  (event: 'delete', message: MessageEnvelope | MessageEnvelope[]): void
  (event: 'requestLoad'): void
}>()

</script>

<template>
  <MemoryMetadataDisclosure
    :created-at="String((message as any)?.created_at || '')"
    :deferred="deferred"
    :loading="loading"
    @request-load="emit('requestLoad')"
  >
    <MemoryMessageParts
      v-if="message"
      :message="message"
      :markdown-preview="markdownPreview"
      :metadata-disclosure="false"
      @save="emit('save', $event)"
      @copy="emit('copy', $event)"
      @delete="emit('delete', $event)"
    />
  </MemoryMetadataDisclosure>
</template>
