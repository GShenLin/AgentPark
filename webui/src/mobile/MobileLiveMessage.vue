<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdownTextWithoutKatex } from '../components/memoryMarkdown'

const props = defineProps<{
  text: string
  thinkingText?: string
  activityText?: string
}>()

const renderedMarkdown = computed(() => renderMarkdownTextWithoutKatex(props.text))
const renderedThinkingMarkdown = computed(() => renderMarkdownTextWithoutKatex(props.thinkingText || ''))
const renderedActivityMarkdown = computed(() => renderMarkdownTextWithoutKatex(props.activityText || ''))
</script>

<template>
  <div class="mobile-live-message">
    <div class="mobile-live-head">
      <span class="mobile-live-role">Live</span>
      <span class="mobile-live-status">streaming</span>
    </div>
    <section v-if="activityText" class="mobile-live-section activity">
      <div class="mobile-live-section-label">Activity</div>
      <div class="mobile-live-body mobile-live-markdown" v-html="renderedActivityMarkdown"></div>
    </section>
    <section v-if="thinkingText" class="mobile-live-section thinking">
      <div class="mobile-live-section-label">Thinking</div>
      <div class="mobile-live-body mobile-live-markdown" v-html="renderedThinkingMarkdown"></div>
    </section>
    <section v-if="text" class="mobile-live-section">
      <div v-if="thinkingText || activityText" class="mobile-live-section-label">Answer</div>
      <div class="mobile-live-body mobile-live-markdown" v-html="renderedMarkdown"></div>
    </section>
  </div>
</template>

<style scoped>
.mobile-live-message {
  flex: 0 0 auto;
  border: 1px solid rgba(125, 211, 252, 0.24);
  border-radius: 8px;
  background: rgba(14, 116, 144, 0.14);
  overflow: hidden;
}

.mobile-live-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-bottom: 1px solid rgba(125, 211, 252, 0.18);
  background: rgba(8, 47, 73, 0.28);
}

.mobile-live-role {
  font-size: 12px;
  font-weight: 700;
}

.mobile-live-status {
  color: rgba(125, 211, 252, 0.9);
  font-size: 11px;
}

.mobile-live-section + .mobile-live-section {
  border-top: 1px solid rgba(125, 211, 252, 0.16);
}

.mobile-live-section.thinking {
  background: rgba(15, 23, 42, 0.22);
}

.mobile-live-section.activity {
  background: rgba(6, 78, 59, 0.18);
}

.mobile-live-section-label {
  padding: 8px 10px 0;
  color: rgba(125, 211, 252, 0.88);
  font-size: 11px;
  font-weight: 700;
}

.mobile-live-body {
  padding: 9px 10px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.5;
  color: rgba(226, 232, 240, 0.96);
  font-size: 14px;
}

.mobile-live-markdown {
  white-space: normal;
}

:deep(.mobile-live-markdown p) {
  margin: 0 0 8px 0;
}

:deep(.mobile-live-markdown p:last-child) {
  margin-bottom: 0;
}

:deep(.mobile-live-markdown pre) {
  max-width: 100%;
  margin: 8px 0;
  padding: 10px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.28);
  overflow: auto;
}

:deep(.mobile-live-markdown code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
}

:deep(.mobile-live-markdown ul),
:deep(.mobile-live-markdown ol) {
  margin: 6px 0 6px 18px;
  padding: 0;
}

:deep(.mobile-live-markdown li) {
  margin: 2px 0;
}
</style>
