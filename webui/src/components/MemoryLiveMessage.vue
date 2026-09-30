<script setup lang="ts">
import { computed } from 'vue'
import type { LiveActivityBlock } from '../api'
import { t } from '../i18n'
import { renderMarkdownTextWithoutKatex } from './memoryMarkdown'
import { handleMarkdownCodeCopyClick } from './markdownCodeCopy'
import LiveActivityBlocks from './LiveActivityBlocks.vue'
import LiveStreamText from './LiveStreamText.vue'

const props = defineProps<{
  liveMessage: string
  thinkingMessage: string
  activityMessage: string
  activityBlocks: LiveActivityBlock[]
  nodeId: string
  graphId: string
  markdownPreview: boolean
  wordWrap: boolean
}>()
const emit = defineEmits<{
  copyMessage: [text: string]
  saveMessage: [text: string]
}>()
const hasLiveActivity = computed(() => !!props.liveMessage || !!props.thinkingMessage || !!props.activityMessage || props.activityBlocks.length > 0)
const renderedActivityMarkdown = computed(() => renderMarkdownTextWithoutKatex(props.activityMessage))
</script>

<template>
  <div v-if="hasLiveActivity" class="live-message">
    <div class="live-head">
      <span class="live-role">{{ t('memory.live') }}</span>
      <span class="live-status">{{ t('memory.streaming') }}</span>
    </div>
    <section v-if="activityMessage" class="live-section activity">
      <div class="live-section-label">{{ t('memory.activity') }}</div>
      <div
        v-if="markdownPreview"
        class="live-body live-markdown"
        v-html="renderedActivityMarkdown"
        @click="handleMarkdownCodeCopyClick"
      ></div>
      <div v-else class="live-body">{{ activityMessage }}</div>
    </section>
    <LiveActivityBlocks :blocks="activityBlocks" :node-id="nodeId" :graph-id="graphId" />
    <section v-if="thinkingMessage" class="live-section thinking">
      <div class="live-section-label">{{ t('memory.thinking') }}</div>
      <LiveStreamText
        :key="`${graphId}/${nodeId}/thinking`"
        :text="thinkingMessage"
        :word-wrap="wordWrap"
        :label="t('memory.thinking')"
        @copy="emit('copyMessage', $event)"
        @save="emit('saveMessage', $event)"
      />
    </section>
    <section v-if="liveMessage" class="live-section">
      <div v-if="thinkingMessage || activityMessage" class="live-section-label">{{ t('memory.answer') }}</div>
      <LiveStreamText
        :key="`${graphId}/${nodeId}/answer`"
        :text="liveMessage"
        :word-wrap="wordWrap"
        :label="t('memory.answer')"
        @copy="emit('copyMessage', $event)"
        @save="emit('saveMessage', $event)"
      />
    </section>
  </div>
</template>

<style scoped>
.live-message {
  flex: 0 0 auto;
  border: 1px solid rgba(56, 189, 248, 0.34);
  border-left: 4px solid rgba(56, 189, 248, 0.75);
  border-radius: 8px;
  background: rgba(8, 47, 73, 0.28);
  overflow: hidden;
}

.live-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border-bottom: 1px solid rgba(125, 211, 252, 0.18);
  background: rgba(3, 105, 161, 0.16);
}

.live-role {
  font-size: var(--theme-panel-memory-panel-font-ui, 12px);
  font-weight: 700;
  color: rgba(186, 230, 253, 0.96);
}

.live-status {
  font-size: var(--theme-panel-memory-panel-font-meta, 11px);
  color: rgba(125, 211, 252, 0.86);
}

.live-section + .live-section {
  border-top: 1px solid rgba(125, 211, 252, 0.16);
}

.live-section.thinking {
  background: rgba(15, 23, 42, 0.24);
}

.live-section.activity {
  background: rgba(6, 78, 59, 0.18);
}

.live-section-label {
  padding: 8px 10px 0;
  color: rgba(125, 211, 252, 0.88);
  font-size: var(--theme-panel-memory-panel-font-small, 11px);
  font-weight: 700;
}

.live-body {
  padding: 10px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
  color: rgba(226, 232, 240, 0.96);
}

.live-markdown {
  white-space: normal;
}

:deep(.live-markdown p) {
  margin: 0 0 8px 0;
}

:deep(.live-markdown p:last-child) {
  margin-bottom: 0;
}

:deep(.live-markdown pre) {
  margin: 8px 0;
  padding: 10px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.28);
  overflow: auto;
}

:deep(.live-markdown .markdown-code-block pre) {
  margin: 0;
  padding: 10px 48px 34px 10px;
  background: transparent;
}

:deep(.live-markdown code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
}

:deep(.live-markdown ul),
:deep(.live-markdown ol) {
  margin: 6px 0 6px 18px;
  padding: 0;
}

:deep(.live-markdown li) {
  margin: 2px 0;
}
</style>
