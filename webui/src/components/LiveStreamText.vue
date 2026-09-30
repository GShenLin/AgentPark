<script setup lang="ts">
import { ref } from 'vue'
import ActionButton from './ActionButton.vue'
import { t } from '../i18n'

defineProps<{
  text: string
  wordWrap: boolean
  label: string
}>()
const emit = defineEmits<{
  copy: [text: string]
  save: [text: string]
}>()
const end = ref<HTMLElement | null>(null)

function scrollToLatest() {
  end.value?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
}
</script>

<template>
  <div class="live-stream-text">
    <div class="log-actions">
      <ActionButton compact @click="emit('copy', text)">{{ t('memory.copyFullText') }}</ActionButton>
      <ActionButton compact @click="emit('save', text)">{{ t('memory.saveFullText') }}</ActionButton>
      <ActionButton compact @click="scrollToLatest">{{ t('memory.jumpToLatest') }}</ActionButton>
    </div>
    <!-- Let the conversation own vertical scrolling; the full text grows in normal flow. -->
    <div class="log-text" :class="{ wrapped: wordWrap }" tabindex="0" role="region" :aria-label="label">{{ text }}</div>
    <div ref="end"></div>
  </div>
</template>

<style scoped>
.live-stream-text {
  padding: 10px;
  color: inherit;
  min-width: 0;
}
.log-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.log-text {
  min-height: 1.55em;
  overflow-x: auto;
  font: inherit;
  line-height: 1.55;
  white-space: pre;
}
.log-text.wrapped {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
