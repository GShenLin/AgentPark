<script setup lang="ts">
import { computed, nextTick, onBeforeUpdate, onUpdated, ref } from 'vue'
import { nodeOpenMarker } from '../nodeOpenDiagnostics'
import { type GraphInfo, type GraphProfile, type LoadMemoryTurnDetails, type LiveActivityBlock, type MessageEnvelope } from '../api'
import ActionButton from './ActionButton.vue'
import FormTextInput from './FormTextInput.vue'
import MemoryMessageFeed from './MemoryMessageFeed.vue'
import MemoryLiveMessage from './MemoryLiveMessage.vue'
import GraphBrowserPanel from './GraphBrowserPanel.vue'
import { handleMarkdownCodeCopyClick } from './markdownCodeCopy'
import { t } from '../i18n'

type MemoryMode = 'agent' | 'file' | 'graph'
type InteractiveInputOptions = {
  appendNewline?: boolean
  sendEof?: boolean
  sendCtrlC?: boolean
}

const props = defineProps<{
  mode: MemoryMode
  memoryText: string
  messages: MessageEnvelope[]
  liveMessage: string
  thinkingMessage: string
  activityMessage: string
  activityBlocks: LiveActivityBlock[]
  nodeId: string
  graphId: string
  markdownPreview: boolean
  wordWrap: boolean
  showLineNumbers: boolean
  agentImages: string[]
  renderedMarkdown: string
  graphNameInput: string
  graphWorkingPathInput: string
  graphLoading: boolean
  graphMemoryClearingId: string
  graphs: GraphInfo[]
  graphProfiles: GraphProfile[]
  selectedGraphProfileId: string
  interactiveSessionId: string
  interactiveInputText: string
  interactiveInputDisabled: boolean
  interactiveSending: boolean
  loadTurnDetails: LoadMemoryTurnDetails
}>()

const emit = defineEmits<{
  (event: 'update:memoryText', value: string): void
  (event: 'update:graphNameInput', value: string): void
  (event: 'update:graphWorkingPathInput', value: string): void
  (event: 'graphPathError', message: string): void
  (event: 'update:selectedGraphProfileId', value: string): void
  (event: 'update:interactiveInputText', value: string): void
  (event: 'saveCurrentFile'): void
  (event: 'saveGraphConfig'): void
  (event: 'saveGraphProfile'): void
  (event: 'createGraphFromProfile'): void
  (event: 'deleteGraphProfile'): void
  (event: 'refreshGraphs'): void
  (event: 'loadGraphConfig', graph: GraphInfo): void
  (event: 'navigateGraphNode', payload: { graph: GraphInfo; nodeId: string }): void
  (event: 'navigateGraphGroup', payload: { graph: GraphInfo; groupId: string }): void
  (event: 'clearGraphMemory', graph: GraphInfo): void
  (event: 'deleteGraphConfig', graph: GraphInfo): void
  (event: 'toggleGraphVisibility', graph: GraphInfo): void
  (event: 'autoScrollChange', value: boolean): void
  (event: 'saveMessage', text: string): void
  (event: 'copyMessage', text: string): void
  (event: 'deleteMessage', target: MessageEnvelope | MessageEnvelope[] | { kind: 'turn'; userMessage: MessageEnvelope }): void
  (event: 'sendInteractiveInput', options: InteractiveInputOptions): void
  (event: 'interactiveSubmit'): void
  (event: 'interactiveCtrlC'): void
  (event: 'interactiveEof'): void
}>()

const memoryPanelRef = ref<HTMLElement | null>(null)
let updateStarted = 0
let updateMarker: ReturnType<typeof nodeOpenMarker> = null
onBeforeUpdate(() => {
  updateMarker = nodeOpenMarker(props.graphId, props.nodeId)
  updateStarted = performance.now()
})
onUpdated(() => {
  const mark = updateMarker
  if (!mark) return
  const flushed = performance.now()
  mark('vue_flush', { duration_ms: flushed - updateStarted, live_chars: props.liveMessage.length, messages: props.messages.length, wrap: Number(props.wordWrap) })
  // Two frame callbacks are a presentation opportunity, not a precise paint timer.
  window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
    mark('frame_after_update', { elapsed_ms: performance.now() - flushed, visible: Number(document.visibilityState === 'visible') })
  }))
})
const gutterRef = ref<HTMLElement | null>(null)
const interactiveInputRef = ref<InstanceType<typeof FormTextInput> | null>(null)

const lines = computed(() => (props.memoryText ? props.memoryText.split(/\r?\n/) : []))
const lineCount = computed(() => (props.memoryText ? lines.value.length : 1))
const showInteractiveBar = computed(() => props.mode === 'agent' && !!props.interactiveSessionId)
const hasLiveActivity = computed(() => !!props.liveMessage || !!props.thinkingMessage || !!props.activityMessage || props.activityBlocks.length > 0)

function updateMemoryText(event: Event) {
  emit('update:memoryText', String((event.target as HTMLTextAreaElement | null)?.value || ''))
}

function updateInteractiveInput(value: string) {
  emit('update:interactiveInputText', value)
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
    const mark = nodeOpenMarker(props.graphId, props.nodeId)
    const started = performance.now()
    const height = panel.scrollHeight
    const measured = performance.now()
    panel.scrollTop = height
    mark?.('scroll_layout', {
      height_read_ms: measured - started, scroll_write_ms: performance.now() - measured,
      scroll_height: height, live_chars: props.liveMessage.length,
    })
  }
}

async function focusInteractiveInput() {
  await nextTick()
  interactiveInputRef.value?.focus()
}

function onInteractiveKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    emit('interactiveSubmit')
  }
}

defineExpose({ scrollToBottom, focusInteractiveInput })
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
    <GraphBrowserPanel v-if="mode === 'graph'" :graph-id="graphId"
      :graph-name-input="graphNameInput" :graph-working-path-input="graphWorkingPathInput"
      :graph-loading="graphLoading" :graph-memory-clearing-id="graphMemoryClearingId"
      :graphs="graphs" :graph-profiles="graphProfiles" :selected-graph-profile-id="selectedGraphProfileId"
      @update:graph-name-input="emit('update:graphNameInput', $event)"
      @update:graph-working-path-input="emit('update:graphWorkingPathInput', $event)"
      @update:selected-graph-profile-id="emit('update:selectedGraphProfileId', $event)"
      @graph-path-error="emit('graphPathError', $event)"
      @save-graph-config="emit('saveGraphConfig')" @save-graph-profile="emit('saveGraphProfile')"
      @create-graph-from-profile="emit('createGraphFromProfile')" @delete-graph-profile="emit('deleteGraphProfile')"
      @refresh-graphs="emit('refreshGraphs')" @load-graph-config="emit('loadGraphConfig', $event)"
      @navigate-graph-node="emit('navigateGraphNode', $event)" @navigate-graph-group="emit('navigateGraphGroup', $event)"
      @clear-graph-memory="emit('clearGraphMemory', $event)" @delete-graph-config="emit('deleteGraphConfig', $event)"
      @toggle-graph-visibility="emit('toggleGraphVisibility', $event)" />

    <div
      v-else-if="mode === 'agent' && (messages.length > 0 || hasLiveActivity || showInteractiveBar)"
      ref="memoryPanelRef"
      class="panel-body message-feed"
      @scroll="syncScroll"
    >
      <MemoryMessageFeed
        :key="`${graphId}:${nodeId}`"
        :messages="messages"
        :markdown-preview="markdownPreview"
        :load-turn-details="loadTurnDetails"
        @save-message="emit('saveMessage', $event)"
        @copy-message="emit('copyMessage', $event)"
        @delete-message="emit('deleteMessage', $event)"
      />
      <MemoryLiveMessage
        :key="`${graphId}:${nodeId}:live`"
        :live-message="liveMessage"
        :thinking-message="thinkingMessage"
        :activity-message="activityMessage"
        :activity-blocks="activityBlocks"
        :node-id="nodeId"
        :graph-id="graphId"
        :markdown-preview="markdownPreview"
        :word-wrap="wordWrap"
        @copy-message="emit('copyMessage', $event)"
        @save-message="emit('saveMessage', $event)"
      />
    </div>

    <div
      v-else-if="markdownPreview"
      ref="memoryPanelRef"
      class="panel-body markdown-body"
      v-html="renderedMarkdown"
      @click="handleMarkdownCodeCopyClick"
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
      <div v-if="lines.length === 0" class="wrap-empty">{{ t('memory.empty') }}</div>
    </div>
  </div>

  <div v-if="showInteractiveBar" class="interactive-bar">
    <div class="interactive-bar-head">
      <span class="interactive-label">{{ t('memory.interactiveInput') }}</span>
      <span class="interactive-hint">{{ t('memory.interactiveHint') }}</span>
    </div>
    <div class="interactive-input-row">
      <FormTextInput
        ref="interactiveInputRef"
        class="interactive-input"
        compact
        :model-value="interactiveInputText"
        :disabled="interactiveInputDisabled"
        :placeholder="t('memory.responsePlaceholder')"
        spellcheck="false"
        @update:model-value="updateInteractiveInput"
        @keydown="onInteractiveKeydown"
      />
      <ActionButton
        compact
        :disabled="interactiveInputDisabled"
        @click="emit('interactiveSubmit')"
      >
        {{ interactiveSending ? '...' : 'Send' }}
      </ActionButton>
      <ActionButton
        compact
        :title="t('memory.interrupt')"
        :disabled="interactiveInputDisabled"
        @click="emit('interactiveCtrlC')"
      >
        Ctrl+C
      </ActionButton>
      <ActionButton
        compact
        :title="t('memory.eof')"
        :disabled="interactiveInputDisabled"
        @click="emit('interactiveEof')"
      >
        EOF
      </ActionButton>
    </div>
  </div>
</template>

<style scoped src="./memoryContentView.css"></style>
