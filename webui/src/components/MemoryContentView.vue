<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { selectFolder, type GraphInfo, type GraphProfile, type LatestTurnProgressSummary, type MessageEnvelope, type NodeInstanceConfig } from '../api'
import MemoryMessageFeed from './MemoryMessageFeed.vue'
import { handleMarkdownCodeCopyClick } from './markdownCodeCopy'
import { renderMarkdownTextWithoutKatex } from './memoryMarkdown'

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
  historyComplete: boolean
  progressLoaded: boolean
  metadataLoaded: boolean
  progressSummary: LatestTurnProgressSummary | null
  loadingSection: 'progress' | 'metadata' | null
  liveMessage: string
  thinkingMessage: string
  activityMessage: string
  markdownPreview: boolean
  wordWrap: boolean
  showLineNumbers: boolean
  agentImages: string[]
  renderedMarkdown: string
  graphNameInput: string
  graphWorkingPathInput: string
  graphLoading: boolean
  graphMemoryClearingId: string
  graphNodesLoadingId: string
  expandedGraphId: string
  graphs: GraphInfo[]
  graphNodesById: Record<string, NodeInstanceConfig[]>
  graphProfiles: GraphProfile[]
  selectedGraphProfileId: string
  interactiveSessionId: string
  interactiveInputText: string
  interactiveInputDisabled: boolean
  interactiveSending: boolean
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
  (event: 'toggleGraphNodes', graph: GraphInfo): void
  (event: 'loadGraphConfig', graph: GraphInfo): void
  (event: 'navigateGraphNode', payload: { graph: GraphInfo; nodeId: string }): void
  (event: 'clearGraphMemory', graph: GraphInfo): void
  (event: 'deleteGraphConfig', graph: GraphInfo): void
  (event: 'toggleGraphVisibility', graph: GraphInfo): void
  (event: 'autoScrollChange', value: boolean): void
  (event: 'saveMessage', text: string): void
  (event: 'copyMessage', text: string): void
  (event: 'deleteMessage', messages: MessageEnvelope | MessageEnvelope[]): void
  (event: 'requestHistory'): void
  (event: 'requestSection', section: 'progress' | 'metadata'): void
  (event: 'sendInteractiveInput', options: InteractiveInputOptions): void
  (event: 'interactiveSubmit'): void
  (event: 'interactiveCtrlC'): void
  (event: 'interactiveEof'): void
}>()

const memoryPanelRef = ref<HTMLElement | null>(null)
const gutterRef = ref<HTMLElement | null>(null)
const interactiveInputRef = ref<HTMLInputElement | null>(null)

const lines = computed(() => (props.memoryText ? props.memoryText.split(/\r?\n/) : []))
const lineCount = computed(() => (props.memoryText ? lines.value.length : 1))
const renderedLiveMarkdown = computed(() => renderMarkdownTextWithoutKatex(props.liveMessage))
const renderedThinkingMarkdown = computed(() => renderMarkdownTextWithoutKatex(props.thinkingMessage))
const renderedActivityMarkdown = computed(() => renderMarkdownTextWithoutKatex(props.activityMessage))
const showInteractiveBar = computed(() => props.mode === 'agent' && !!props.interactiveSessionId)
const hasLiveActivity = computed(() => !!props.liveMessage || !!props.thinkingMessage || !!props.activityMessage)

function canDeleteGraph(graph: GraphInfo) {
  if (typeof graph.deletable === 'boolean') return graph.deletable
  return !graph.readonly
}

function graphNodeLabel(node: NodeInstanceConfig) {
  return String(node.name || node.node_id || '').trim() || 'Unnamed node'
}

function graphNodeMeta(node: NodeInstanceConfig) {
  const typeId = String(node.type_id || '').trim()
  const nodeId = String(node.node_id || '').trim()
  if (typeId && nodeId && typeId !== nodeId) return `${typeId} - ${nodeId}`
  return typeId || nodeId
}

function graphNodes(graphId: string) {
  return props.graphNodesById[String(graphId || '').trim()] || []
}

function onGraphInfoClick(graph: GraphInfo) {
  emit('toggleGraphNodes', graph)
}

function onGraphInfoKeydown(graph: GraphInfo, event: KeyboardEvent) {
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  emit('toggleGraphNodes', graph)
}

function updateMemoryText(event: Event) {
  emit('update:memoryText', String((event.target as HTMLTextAreaElement | null)?.value || ''))
}

function updateGraphName(event: Event) {
  emit('update:graphNameInput', String((event.target as HTMLInputElement | null)?.value || ''))
}

function updateGraphWorkingPath(event: Event) {
  emit('update:graphWorkingPathInput', String((event.target as HTMLInputElement | null)?.value || ''))
}

async function chooseGraphWorkingPath() {
  try {
    const res = await selectFolder(String(props.graphWorkingPathInput || ''))
    const selectedPath = String(res?.path || '').trim()
    if (selectedPath) {
      emit('update:graphWorkingPathInput', selectedPath)
      await nextTick()
      emit('saveGraphConfig')
    }
  } catch (e: any) {
    emit('graphPathError', String(e?.message || e))
  }
}

function updateSelectedGraphProfile(event: Event) {
  emit('update:selectedGraphProfileId', String((event.target as HTMLSelectElement | null)?.value || ''))
}

function updateInteractiveInput(event: Event) {
  emit('update:interactiveInputText', String((event.target as HTMLInputElement | null)?.value || ''))
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
    <div v-if="mode === 'graph'" class="graph-panel">
      <div class="graph-actions">
        <input
          class="graph-input"
          placeholder="Graph name"
          :value="graphNameInput"
          @input="updateGraphName"
        />
        <button class="graph-btn primary" @click="emit('saveGraphConfig')">Save</button>
        <button class="graph-btn" @click="emit('saveGraphProfile')">SaveProfile</button>
        <button class="graph-btn" @click="emit('refreshGraphs')">Refresh</button>
      </div>
      <div class="graph-path-row">
        <input
          class="graph-input graph-path-input"
          placeholder="Graph working path"
          :value="graphWorkingPathInput"
          @input="updateGraphWorkingPath"
          @blur="emit('saveGraphConfig')"
        />
        <button class="graph-btn" type="button" @click="chooseGraphWorkingPath">ChangeFolder</button>
      </div>
      <div class="graph-actions">
        <select
          class="graph-input profile-input"
          :value="selectedGraphProfileId"
          @change="updateSelectedGraphProfile"
        >
          <option value="">Profile</option>
          <option v-for="profile in graphProfiles" :key="profile.id" :value="profile.id">
            {{ profile.name || profile.id }}
          </option>
        </select>
        <button
          class="graph-btn primary"
          :disabled="!selectedGraphProfileId"
          @click="emit('createGraphFromProfile')"
        >
          CreateFromProfile
        </button>
        <button
          class="graph-btn danger"
          :disabled="!selectedGraphProfileId"
          @click="emit('deleteGraphProfile')"
        >
          DeleteProfile
        </button>
      </div>

      <div class="graph-list">
        <div v-if="graphLoading" class="graph-empty">Loading graphs...</div>
        <div v-else-if="graphs.length === 0" class="graph-empty">No saved graph found.</div>
        <div v-else class="graph-items">
          <div v-for="graph in graphs" :key="graph.id" class="graph-item-shell">
            <div class="graph-item">
              <div
                class="graph-info graph-info-clickable"
                tabindex="0"
                role="button"
                :aria-expanded="expandedGraphId === graph.id"
                @click="onGraphInfoClick(graph)"
                @keydown="onGraphInfoKeydown(graph, $event)"
              >
                <div class="graph-name-row">
                  <span class="graph-expander">{{ expandedGraphId === graph.id ? '-' : '+' }}</span>
                  <div class="graph-name">{{ graph.name }}</div>
                </div>
                <div class="graph-meta">{{ graph.updated_at || graph.id }}</div>
              </div>
              <div class="graph-item-actions">
                <button
                  v-if="graph.visibility_editable"
                  class="graph-btn"
                  @click="emit('toggleGraphVisibility', graph)"
                >
                  {{ graph.private ? 'Public' : 'Private' }}
                </button>
                <button class="graph-btn" @click="emit('loadGraphConfig', graph)">Load</button>
                <button
                  class="graph-btn danger"
                  :disabled="graphMemoryClearingId === graph.id"
                  @click="emit('clearGraphMemory', graph)"
                >
                  {{ graphMemoryClearingId === graph.id ? 'Clearing...' : 'ClearMemory' }}
                </button>
                <button v-if="canDeleteGraph(graph)" class="graph-btn danger" @click="emit('deleteGraphConfig', graph)">Delete</button>
              </div>
            </div>
            <div v-if="expandedGraphId === graph.id" class="graph-node-list">
              <div v-if="graphNodesLoadingId === graph.id" class="graph-node-empty">Loading nodes...</div>
              <div v-else-if="graphNodes(graph.id).length === 0" class="graph-node-empty">No node found.</div>
              <template v-else>
                <button
                  v-for="node in graphNodes(graph.id)"
                  :key="node.node_id"
                  type="button"
                  class="graph-node-item"
                  @click="emit('navigateGraphNode', { graph, nodeId: node.node_id })"
                >
                  <span class="graph-node-name">{{ graphNodeLabel(node) }}</span>
                  <span class="graph-node-meta">{{ graphNodeMeta(node) }}</span>
                </button>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div
      v-else-if="mode === 'agent' && (messages.length > 0 || hasLiveActivity || showInteractiveBar)"
      ref="memoryPanelRef"
      class="panel-body message-feed"
      @scroll="syncScroll"
    >
      <MemoryMessageFeed
        :messages="messages"
        :markdown-preview="markdownPreview"
        :history-complete="historyComplete"
        :progress-loaded="progressLoaded"
        :metadata-loaded="metadataLoaded"
        :progress-summary="progressSummary"
        :loading-section="loadingSection"
        @save-message="emit('saveMessage', $event)"
        @copy-message="emit('copyMessage', $event)"
        @delete-message="emit('deleteMessage', $event)"
        @request-history="emit('requestHistory')"
        @request-section="emit('requestSection', $event)"
      />
      <div v-if="hasLiveActivity" class="live-message">
        <div class="live-head">
          <span class="live-role">Live</span>
          <span class="live-status">streaming</span>
        </div>
        <section v-if="activityMessage" class="live-section activity">
          <div class="live-section-label">Activity</div>
          <div
            v-if="markdownPreview"
            class="live-body live-markdown"
            v-html="renderedActivityMarkdown"
            @click="handleMarkdownCodeCopyClick"
          ></div>
          <div v-else class="live-body">{{ activityMessage }}</div>
        </section>
        <section v-if="thinkingMessage" class="live-section thinking">
          <div class="live-section-label">Thinking</div>
          <div
            v-if="markdownPreview"
            class="live-body live-markdown"
            v-html="renderedThinkingMarkdown"
            @click="handleMarkdownCodeCopyClick"
          ></div>
          <div v-else class="live-body">{{ thinkingMessage }}</div>
        </section>
        <section v-if="liveMessage" class="live-section">
          <div v-if="thinkingMessage || activityMessage" class="live-section-label">Answer</div>
        <div
          v-if="markdownPreview"
          class="live-body live-markdown"
          v-html="renderedLiveMarkdown"
          @click="handleMarkdownCodeCopyClick"
        ></div>
        <div v-else class="live-body">{{ liveMessage }}</div>
        </section>
      </div>
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
      <div v-if="lines.length === 0" class="wrap-empty">(empty)</div>
    </div>
  </div>

  <div v-if="showInteractiveBar" class="interactive-bar">
    <div class="interactive-bar-head">
      <span class="interactive-label">Interactive Input</span>
      <span class="interactive-hint">Enter to send, input is sent with newline appended</span>
    </div>
    <div class="interactive-input-row">
      <input
        ref="interactiveInputRef"
        class="interactive-input"
        :value="interactiveInputText"
        :disabled="interactiveInputDisabled"
        placeholder="Type response here (e.g. YES, NO, password)..."
        spellcheck="false"
        @input="updateInteractiveInput"
        @keydown="onInteractiveKeydown"
      />
      <button
        class="interactive-btn"
        :disabled="interactiveInputDisabled"
        @click="emit('interactiveSubmit')"
      >
        {{ interactiveSending ? '...' : 'Send' }}
      </button>
      <button
        class="interactive-btn"
        title="Send Ctrl+C (interrupt)"
        :disabled="interactiveInputDisabled"
        @click="emit('interactiveCtrlC')"
      >
        Ctrl+C
      </button>
      <button
        class="interactive-btn"
        title="Send EOF / Ctrl+D (close stdin)"
        :disabled="interactiveInputDisabled"
        @click="emit('interactiveEof')"
      >
        EOF
      </button>
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
  background-color: var(--theme-panel-graph-panel-background-color, transparent);
  background-image: var(--theme-panel-graph-panel-background-image, none);
  background-size: var(--theme-panel-graph-panel-background-size, cover);
  background-position: var(--theme-panel-graph-panel-background-position, center);
  background-repeat: var(--theme-panel-graph-panel-background-repeat, no-repeat);
  background-blend-mode: var(--theme-panel-graph-panel-background-blend-mode, normal);
}

.graph-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.graph-path-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.graph-path-input {
  min-width: 0;
}

.graph-input {
  flex: 1;
  border: 1px solid var(--theme-panel-graph-panel-input-border, rgba(148, 163, 184, 0.3));
  background: var(--theme-panel-graph-panel-input-background, rgba(15, 23, 42, 0.7));
  color: var(--theme-panel-graph-panel-input-text, rgba(226, 232, 240, 0.96));
  border-radius: 8px;
  font-size: 12px;
  padding: 7px 9px;
  outline: none;
}

.graph-input:focus {
  border-color: var(--theme-panel-graph-panel-input-focus-border, rgba(56, 189, 248, 0.7));
}

.graph-btn {
  border: 1px solid var(--theme-panel-graph-panel-button-border, rgba(148, 163, 184, 0.3));
  background: var(--theme-panel-graph-panel-button-background, rgba(15, 23, 42, 0.7));
  color: var(--theme-panel-graph-panel-button-text, rgba(226, 232, 240, 0.94));
  border-radius: 8px;
  font-size: 11px;
  padding: 4px 9px;
  cursor: pointer;
}

.graph-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.profile-input {
  min-width: 0;
}

.graph-btn.primary {
  border-color: var(--theme-panel-graph-panel-button-primary-border, rgba(56, 189, 248, 0.7));
  background: var(--theme-panel-graph-panel-button-primary-background, rgba(14, 116, 144, 0.34));
}

.graph-btn.danger {
  border-color: var(--theme-panel-graph-panel-button-danger-border, rgba(248, 113, 113, 0.7));
  background: var(--theme-panel-graph-panel-button-danger-background, rgba(127, 29, 29, 0.35));
  color: var(--theme-panel-graph-panel-button-danger-text, rgba(254, 226, 226, 0.96));
}

.graph-item-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.graph-list,
.graph-items {
  gap: 8px;
}

.graph-item-shell {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.graph-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid var(--theme-panel-graph-panel-item-border, rgba(148, 163, 184, 0.2));
  border-radius: 10px;
  background: var(--theme-panel-graph-panel-item-background, rgba(15, 23, 42, 0.45));
  padding: 8px 9px;
}

.graph-info {
  min-width: 0;
}

.graph-info-clickable {
  flex: 1;
  cursor: pointer;
  border-radius: 6px;
  padding: 2px 4px;
  margin: -2px -4px;
  outline: none;
}

.graph-info-clickable:hover,
.graph-info-clickable:focus-visible {
  background: rgba(56, 189, 248, 0.1);
}

.graph-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.graph-expander {
  width: 14px;
  flex: 0 0 14px;
  color: var(--theme-panel-graph-panel-item-muted, rgba(148, 163, 184, 0.9));
  text-align: center;
  font-size: 12px;
}

.graph-name {
  font-size: 13px;
  color: var(--theme-panel-graph-panel-item-text, rgba(248, 250, 252, 0.95));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.graph-node-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-left: 16px;
  padding-left: 10px;
  border-left: 1px solid var(--theme-panel-graph-panel-item-border, rgba(148, 163, 184, 0.2));
}

.graph-node-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--theme-panel-graph-panel-item-text, rgba(248, 250, 252, 0.95));
  border-radius: 7px;
  padding: 6px 8px;
  cursor: pointer;
  text-align: left;
}

.graph-node-item:hover,
.graph-node-item:focus-visible {
  border-color: var(--theme-panel-graph-panel-button-primary-border, rgba(56, 189, 248, 0.55));
  background: rgba(14, 116, 144, 0.2);
  outline: none;
}

.graph-node-name {
  max-width: 100%;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.graph-node-meta,
.graph-node-empty {
  max-width: 100%;
  font-size: 11px;
  color: var(--theme-panel-graph-panel-item-muted, rgba(148, 163, 184, 0.9));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.graph-node-empty {
  padding: 6px 8px;
}

.graph-meta,
.graph-empty {
  font-size: 11px;
  color: var(--theme-panel-graph-panel-item-muted, rgba(148, 163, 184, 0.9));
}

.line-gutter {
  width: 52px;
  background: rgba(0, 0, 0, 0.2);
  border-right: 1px solid rgba(148, 163, 184, 0.14);
  color: rgba(148, 163, 184, 0.8);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: var(--theme-panel-memory-panel-font-ui, 12px);
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
  color: var(--theme-panel-memory-panel-text-secondary, #e2e8f0);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: var(--theme-panel-memory-panel-font-body, 13px);
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

.interactive-bar {
  flex: 0 0 auto;
  border-top: 1px solid rgba(34, 211, 238, 0.22);
  background: rgba(8, 47, 73, 0.32);
  padding: 8px 10px;
}

.interactive-bar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.interactive-label {
  font-size: var(--theme-panel-memory-panel-font-small, 11px);
  font-weight: 700;
  color: rgba(103, 232, 249, 0.96);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.interactive-hint {
  font-size: var(--theme-panel-memory-panel-font-small, 11px);
  color: rgba(148, 163, 184, 0.82);
}

.interactive-input-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.interactive-input {
  flex: 1;
  min-width: 0;
  border: 1px solid rgba(34, 211, 238, 0.32);
  background: rgba(15, 23, 42, 0.82);
  color: rgba(226, 232, 240, 0.96);
  border-radius: 8px;
  font-size: var(--theme-panel-memory-panel-font-ui, 12px);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  padding: 7px 9px;
  outline: none;
}

.interactive-input:focus {
  border-color: rgba(34, 211, 238, 0.65);
}

.interactive-input:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.interactive-btn {
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(15, 23, 42, 0.82);
  color: rgba(226, 232, 240, 0.94);
  border-radius: 8px;
  font-size: var(--theme-panel-memory-panel-font-small, 11px);
  padding: 6px 10px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

.interactive-btn:hover:not(:disabled) {
  border-color: rgba(34, 211, 238, 0.5);
  background: rgba(14, 116, 144, 0.28);
}

.interactive-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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
  font-size: var(--theme-panel-memory-panel-font-ui, 12px);
  line-height: 1.5;
}

.wrap-content {
  flex: 1;
  padding: 0 12px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: var(--theme-panel-memory-panel-font-body, 13px);
  line-height: 1.5;
  color: inherit;
}

.wrap-empty {
  padding: 10px 60px;
  opacity: 0.6;
  font-size: var(--theme-panel-memory-panel-font-ui, 12px);
}

@media (max-width: 760px) {
  .interactive-bar-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }

  .interactive-input-row {
    flex-wrap: wrap;
  }

  .interactive-input {
    min-width: 0;
    width: 100%;
  }
}
</style>
