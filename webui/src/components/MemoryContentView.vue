<script setup lang="ts">
import { computed, ref } from 'vue'
import type { GraphInfo, MessageEnvelope } from '../api'
import MemoryMessageFeed from './MemoryMessageFeed.vue'
import { renderMarkdownTextWithoutKatex } from './memoryMarkdown'

type MemoryMode = 'agent' | 'file' | 'graph'

const props = defineProps<{
  mode: MemoryMode
  memoryText: string
  messages: MessageEnvelope[]
  liveMessage: string
  markdownPreview: boolean
  wordWrap: boolean
  showLineNumbers: boolean
  agentImages: string[]
  renderedMarkdown: string
  graphNameInput: string
  graphLoading: boolean
  graphs: GraphInfo[]
}>()

const emit = defineEmits<{
  (event: 'update:memoryText', value: string): void
  (event: 'update:graphNameInput', value: string): void
  (event: 'saveCurrentFile'): void
  (event: 'saveGraphConfig'): void
  (event: 'refreshGraphs'): void
  (event: 'loadGraphConfig', graph: GraphInfo): void
  (event: 'deleteGraphConfig', graph: GraphInfo): void
  (event: 'autoScrollChange', value: boolean): void
  (event: 'saveMessage', text: string): void
  (event: 'copyMessage', text: string): void
  (event: 'deleteMessage', message: MessageEnvelope): void
}>()

const memoryPanelRef = ref<HTMLElement | null>(null)
const gutterRef = ref<HTMLElement | null>(null)

const lines = computed(() => (props.memoryText ? props.memoryText.split(/\r?\n/) : []))
const lineCount = computed(() => (props.memoryText ? lines.value.length : 1))
const renderedLiveMarkdown = computed(() => renderMarkdownTextWithoutKatex(props.liveMessage))

function updateMemoryText(event: Event) {
  emit('update:memoryText', String((event.target as HTMLTextAreaElement | null)?.value || ''))
}

function updateGraphName(event: Event) {
  emit('update:graphNameInput', String((event.target as HTMLInputElement | null)?.value || ''))
}

function syncScroll(event: Event) {
  const target = event.target as HTMLElement
  if (gutterRef.value) {
    gutterRef.value.scrollTop = target.scrollTop
  }
  const remaining = target.scrollHeight - target.scrollTop - target.clientHeight
  emit('autoScrollChange', remaining < 16)
}

function scrollToBottom() {
  const panel = memoryPanelRef.value
  if (panel) {
    panel.scrollTop = panel.scrollHeight
  }
}

defineExpose({ scrollToBottom })
</script>

<template>
  <div v-if="agentImages.length > 0 && mode === 'agent'" class="agent-images">
    <div v-for="img in agentImages" :key="img" class="agent-image-item">
      <a :href="`/memories/${img}`" target="_blank" rel="noreferrer">
        <img :src="`/memories/${img}`" :alt="img" />
      </a>
    </div>
  </div>

  <div class="editor-wrapper">
    <div v-if="mode === 'graph'" class="graph-panel">
      <div class="graph-actions">
        <input
          class="graph-input"
          placeholder="Graph name"
          :value="graphNameInput"
          @input="updateGraphName"
        />
        <button class="graph-btn primary" @click="emit('saveGraphConfig')">Save</button>
        <button class="graph-btn" @click="emit('refreshGraphs')">Refresh</button>
      </div>

      <div class="graph-list">
        <div v-if="graphLoading" class="graph-empty">Loading graphs...</div>
        <div v-else-if="graphs.length === 0" class="graph-empty">No saved graph found.</div>
        <div v-else class="graph-items">
          <div v-for="graph in graphs" :key="graph.id" class="graph-item">
            <div class="graph-info">
              <div class="graph-name">{{ graph.name }}</div>
              <div class="graph-meta">{{ graph.updated_at || graph.id }}</div>
            </div>
            <div class="graph-item-actions">
              <button class="graph-btn" @click="emit('loadGraphConfig', graph)">Load</button>
              <button class="graph-btn danger" @click="emit('deleteGraphConfig', graph)">Delete</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div
      v-else-if="mode === 'agent' && (messages.length > 0 || liveMessage)"
      ref="memoryPanelRef"
      class="panel-body message-feed"
      @scroll="syncScroll"
    >
      <MemoryMessageFeed
        :messages="messages"
        :markdown-preview="markdownPreview"
        @save-message="emit('saveMessage', $event)"
        @copy-message="emit('copyMessage', $event)"
        @delete-message="emit('deleteMessage', $event)"
      />
      <div v-if="liveMessage" class="live-message">
        <div class="live-head">
          <span class="live-role">Live</span>
          <span class="live-status">streaming</span>
        </div>
        <div
          v-if="markdownPreview"
          class="live-body live-markdown"
          v-html="renderedLiveMarkdown"
        ></div>
        <div v-else class="live-body">{{ liveMessage }}</div>
      </div>
    </div>

    <div
      v-else-if="markdownPreview"
      ref="memoryPanelRef"
      class="panel-body markdown-body"
      v-html="renderedMarkdown"
      @scroll="syncScroll"
    ></div>

    <template v-else-if="!wordWrap">
      <div v-if="showLineNumbers" ref="gutterRef" class="line-gutter">
        <div v-for="n in lineCount" :key="n" class="line-number">{{ n }}</div>
      </div>

      <textarea
        v-if="mode === 'file'"
        ref="memoryPanelRef"
        class="panel-body file-editor"
        :value="memoryText"
        spellcheck="false"
        wrap="off"
        @input="updateMemoryText"
        @blur="emit('saveCurrentFile')"
        @scroll="syncScroll"
      ></textarea>

      <pre
        v-else
        ref="memoryPanelRef"
        class="panel-body"
        @scroll="syncScroll"
      >{{ memoryText || '(empty)' }}</pre>
    </template>

    <div v-else ref="memoryPanelRef" class="wrap-container" :class="{ 'no-gutter': !showLineNumbers }" @scroll="syncScroll">
      <div v-for="(line, index) in lines" :key="index" class="wrap-row">
        <div v-if="showLineNumbers" class="wrap-num">{{ index + 1 }}</div>
        <div class="wrap-content">{{ line || ' ' }}</div>
      </div>
      <div v-if="lines.length === 0" class="wrap-empty">(empty)</div>
    </div>
  </div>
</template>

<style scoped>
.agent-images {
  padding: 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-height: 180px;
  overflow-y: auto;
}

.agent-image-item {
  width: 94px;
  height: 94px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.3);
}

.agent-image-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.editor-wrapper,
.graph-panel,
.graph-list,
.graph-items {
  display: flex;
}

.editor-wrapper {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.graph-panel,
.graph-list,
.graph-items {
  flex-direction: column;
}

.graph-panel {
  flex: 1;
  gap: 10px;
  padding: 10px;
  overflow: auto;
}

.graph-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.graph-input {
  flex: 1;
  border: 1px solid rgba(148, 163, 184, 0.3);
  background: rgba(15, 23, 42, 0.7);
  color: rgba(226, 232, 240, 0.96);
  border-radius: 8px;
  font-size: 12px;
  padding: 7px 9px;
  outline: none;
}

.graph-input:focus {
  border-color: rgba(56, 189, 248, 0.7);
}

.graph-btn {
  border: 1px solid rgba(148, 163, 184, 0.3);
  background: rgba(15, 23, 42, 0.7);
  color: rgba(226, 232, 240, 0.94);
  border-radius: 8px;
  font-size: 11px;
  padding: 4px 9px;
}

.graph-btn.primary {
  border-color: rgba(56, 189, 248, 0.7);
  background: rgba(14, 116, 144, 0.34);
}

.graph-btn.danger {
  border-color: rgba(248, 113, 113, 0.7);
  background: rgba(127, 29, 29, 0.35);
  color: rgba(254, 226, 226, 0.96);
}

.graph-item-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.graph-list,
.graph-items {
  gap: 8px;
}

.graph-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.45);
  padding: 8px 9px;
}

.graph-info {
  min-width: 0;
}

.graph-name {
  font-size: 13px;
  color: rgba(248, 250, 252, 0.95);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.graph-meta,
.graph-empty {
  font-size: 11px;
  color: rgba(148, 163, 184, 0.9);
}

.line-gutter {
  width: 52px;
  background: rgba(0, 0, 0, 0.2);
  border-right: 1px solid rgba(148, 163, 184, 0.14);
  color: rgba(148, 163, 184, 0.8);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 12px;
  text-align: right;
  padding: 10px 8px;
  overflow: hidden;
  user-select: none;
  flex-shrink: 0;
  line-height: 1.5;
}

.line-number {
  line-height: 1.5;
}

.panel-body {
  flex: 1;
  min-height: 0;
  margin: 0;
  padding: 12px;
  border: none;
  background: transparent;
  color: #e2e8f0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 13px;
  line-height: 1.5;
  resize: none;
  outline: none;
  overflow: auto;
  white-space: pre;
  scrollbar-gutter: stable both-edges;
}

.message-feed {
  display: flex;
  flex-direction: column;
  gap: 10px;
  white-space: normal;
  min-height: 0;
  max-height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
}

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
  font-size: 12px;
  font-weight: 700;
  color: rgba(186, 230, 253, 0.96);
}

.live-status {
  font-size: 11px;
  color: rgba(125, 211, 252, 0.86);
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

.wrap-container {
  flex: 1;
  overflow: auto;
  padding: 10px 0;
  position: relative;
}

.wrap-container::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 52px;
  background: rgba(0, 0, 0, 0.2);
  border-right: 1px solid rgba(148, 163, 184, 0.14);
  pointer-events: none;
}

.wrap-container.no-gutter::before {
  display: none;
}

.wrap-row {
  display: flex;
  position: relative;
  z-index: 1;
}

.wrap-num {
  width: 52px;
  flex-shrink: 0;
  text-align: right;
  padding-right: 8px;
  color: rgba(148, 163, 184, 0.78);
  user-select: none;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 12px;
  line-height: 1.5;
}

.wrap-content {
  flex: 1;
  padding: 0 12px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 13px;
  line-height: 1.5;
  color: inherit;
}

.wrap-empty {
  padding: 10px 60px;
  opacity: 0.6;
  font-size: 12px;
}
</style>
