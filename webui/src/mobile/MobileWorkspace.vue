<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { MessageEnvelope, MobileNode, ResourceKind } from '../api'
import { restartServer } from '../api'
import { uploadFiles, type UploadedFileItem } from '../uploadApi'
import MemoryToolCallPart from '../components/MemoryToolCallPart.vue'
import MemorySaveDialog from '../components/MemorySaveDialog.vue'
import {
  lastToolInstruction,
  toolDuration,
  toolGroupLabel,
  toolGroupParts,
  toolGroupTime,
  toolName,
  toolStatus,
  useMemoryFeedEntries,
} from '../components/memoryFeedTools'
import MobileLiveMessage from './MobileLiveMessage.vue'
import MobileMessageText from './MobileMessageText.vue'
import MobileNodeCreateDialog from './MobileNodeCreateDialog.vue'
import MobileNodeConfigDialog from './MobileNodeConfigDialog.vue'
import MobileNodeListItem from './MobileNodeListItem.vue'
import SettingsPage from '../components/SettingsPage.vue'
import { useMemoryMessageExport } from '../composables/useMemoryMessageExport'
import { useMobileWorkspace } from './useMobileWorkspace'
import { buildMessageSignature, messageRoleClass } from './mobileMessageRender'
import { extractMemoryMessageText } from '../components/memoryMessageText'

const workspace = useMobileWorkspace()
const {
  saveDialogOpen,
  saveDialogFilename,
  saveDialogTargetDir,
  saveDialogError,
  saveDialogSaving,
  openSaveMessageDialog,
  confirmSaveMessageDialog,
  cancelSaveMessageDialog,
  copyMessageText,
} = useMemoryMessageExport()
const draft = ref('')
const feedRef = ref<HTMLElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const attachments = ref<UploadedFileItem[]>([])
const uploadingFiles = ref(false)
const configOpen = ref(false)
const createNodeOpen = ref(false)
const settingsOpen = ref(false)
const isRestarting = ref(false)
const graphNameInput = ref('')
const graphStatus = ref('')
const graphSaving = ref(false)
const goalArmedByNode = ref<Record<string, boolean>>({})
const expandedToolGroups = ref<Set<string>>(new Set())
const SCROLL_STICK_THRESHOLD = 48

const headerTitle = computed(() => {
  if (settingsOpen.value) return 'Settings'
  if (workspace.view.value === 'pcs') return '选择 PC'
  if (workspace.view.value === 'graphs') return workspace.selectedPc.value?.name || '选择 Graph'
  if (workspace.view.value === 'nodes') return workspace.selectedGraph.value?.display_name || '选择节点'
  return workspace.selectedNode.value?.name || workspace.selectedNode.value?.id || '节点消息'
})

const messages = computed(() => workspace.conversation.value?.messages || [])
const feedEntries = useMemoryFeedEntries(messages)
const liveMessage = computed(() => String(workspace.conversation.value?.live_message || ''))
const messageSignature = computed(() => buildMessageSignature(messages.value))
const selectedGoalState = computed(() => {
  const state = workspace.selectedConfig.value?.goal_state
  return state && typeof state === 'object' ? state as Record<string, unknown> : null
})
const selectedGoalText = computed(() => String(workspace.selectedConfig.value?.goal || '').trim())
const hasPersistedGoal = computed(() => !!(selectedGoalText.value || selectedGoalState.value))
const isAgentNode = computed(() => workspace.selectedNode.value?.type_id === 'agent_node')
const goalEnabled = computed(() => isAgentNode.value || hasPersistedGoal.value)
const goalActive = computed(() => {
  const id = String(workspace.selectedNode.value?.id || '').trim()
  return goalEnabled.value && (!!(id && goalArmedByNode.value[id]) || hasPersistedGoal.value)
})
const goalTitle = computed(() => {
  const status = String(selectedGoalState.value?.status || '').trim()
  const reason = String(selectedGoalState.value?.reason || '').trim()
  if (selectedGoalText.value) {
    return reason ? `Goal ${status || 'set'}: ${reason}` : `Goal ${status || 'set'}`
  }
  if (!isAgentNode.value) return 'Goal mode is available on Agent nodes'
  return goalActive.value ? 'Disable goal mode' : 'Enable goal mode'
})

function nodeStateLabel(node: MobileNode) {
  const state = String(node.state || 'idle')
  if (state === 'working') return '工作中'
  if (state === 'stop') return '已停止'
  return '空闲'
}

function nodeStateClass(node: MobileNode) {
  const state = String(node.state || 'idle')
  if (state === 'working') return 'state-working'
  if (state === 'stop') return 'state-stop'
  return 'state-idle'
}

function isToolGroupExpanded(key: string) {
  return expandedToolGroups.value.has(key)
}

function toggleToolGroup(key: string) {
  const next = new Set(expandedToolGroups.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedToolGroups.value = next
}

async function sendDraft() {
  const text = draft.value.trim()
  if (!text && attachments.value.length === 0) return
  const payload = composeDraftPayload(text)
  try {
    await persistGoalForSend(payload)
    draft.value = ''
    attachments.value = []
    await workspace.sendMessage(payload)
    await nextTick()
    scrollFeedToBottom()
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  }
}

function openFilePicker() {
  fileInputRef.value?.click()
}

async function onFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || []).filter((file) => file instanceof File)
  input.value = ''
  if (!files.length) return
  uploadingFiles.value = true
  workspace.error.value = ''
  try {
    const uploaded = await uploadFiles(files, 'mobile-node-chat')
    for (const item of uploaded.files || []) {
      if (!attachments.value.some((existing) => existing.path === item.path)) {
        attachments.value.push(item)
      }
    }
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  } finally {
    uploadingFiles.value = false
  }
}

function removeAttachment(index: number) {
  attachments.value.splice(index, 1)
}

function clearAttachments() {
  attachments.value = []
}

function guessResourceKind(item: UploadedFileItem): ResourceKind | 'file' {
  const kind = String(item.kind || '').trim().toLowerCase()
  if (kind === 'image' || kind === 'video' || kind === 'audio' || kind === 'doc' || kind === 'url') return kind
  const mime = String(item.mime || '').toLowerCase()
  if (mime.startsWith('image/')) return 'image'
  if (mime.startsWith('video/')) return 'video'
  if (mime.startsWith('audio/')) return 'audio'
  const lower = String(item.path || item.name || '').toLowerCase()
  if (/\.(png|jpg|jpeg|webp|gif|bmp|svg)$/.test(lower)) return 'image'
  if (/\.(mp4|mov|mkv|webm|avi|flv|m4v)$/.test(lower)) return 'video'
  if (/\.(mp3|wav|ogg|flac|m4a)$/.test(lower)) return 'audio'
  if (/\.(pdf|doc|docx|ppt|pptx|xls|xlsx|txt|md)$/.test(lower)) return 'doc'
  return 'file'
}

function composeDraftPayload(text: string): string | MessageEnvelope {
  if (!attachments.value.length) return text
  const parts: MessageEnvelope['parts'] = []
  if (text) parts.push({ type: 'text', text })
  for (const file of attachments.value) {
    const uri = String(file.path || '').trim()
    if (!uri) continue
    parts.push({
      type: 'resource',
      resource: {
        uri,
        name: String(file.name || ''),
        kind: guessResourceKind(file),
        mime: String(file.mime || ''),
        source: 'mobile_chat',
      },
    })
  }
  return { role: 'user', parts }
}

function payloadGoalText(payload: string | MessageEnvelope) {
  if (typeof payload === 'string') return payload.trim()
  const parts = Array.isArray(payload?.parts) ? payload.parts : []
  const texts: string[] = []
  for (const part of parts) {
    if (!part || typeof part !== 'object') continue
    if (part.type === 'text') {
      const text = String((part as any).text || '').trim()
      if (text) texts.push(text)
    } else if (part.type === 'resource') {
      const resource = (part as any).resource
      const uri = String(resource?.uri || '').trim()
      if (uri) texts.push(`[${String(resource?.kind || 'file')}] ${uri}`)
    } else if (part.type === 'structured') {
      texts.push(JSON.stringify((part as any).data))
    }
  }
  return texts.join('\n').trim()
}

async function persistGoalForSend(payload: string | MessageEnvelope) {
  if (!goalActive.value || !isAgentNode.value) return
  const objective = payloadGoalText(payload)
  if (!objective) {
    throw new Error('Goal mode requires non-empty input.')
  }
  await workspace.setSelectedNodeFields({
    goal: objective,
    goal_state: {
      status: 'active',
      reason: 'Goal started from mobile input.',
      turn_count: 0,
      updated_at: new Date().toISOString(),
    },
  })
}

async function toggleGoal() {
  const nodeId = String(workspace.selectedNode.value?.id || '').trim()
  if (!nodeId || !goalEnabled.value) return
  workspace.error.value = ''
  try {
    if (goalActive.value) {
      goalArmedByNode.value = { ...goalArmedByNode.value, [nodeId]: false }
      await workspace.clearSelectedNodeFields(['goal', 'goal_state'])
    } else {
      goalArmedByNode.value = { ...goalArmedByNode.value, [nodeId]: true }
    }
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  }
}

async function openConfig() {
  if (workspace.view.value !== 'chat' || !workspace.selectedNode.value) return
  configOpen.value = true
  await workspace.refreshNodeConfigs().catch((e: any) => {
    workspace.error.value = String(e?.message || e)
  })
}

function openSettings() {
  if (workspace.view.value !== 'graphs') return
  settingsOpen.value = true
}

function closeSettings() {
  settingsOpen.value = false
}

async function saveMobileGraph() {
  const name = graphNameInput.value.trim()
  if (!name) {
    graphStatus.value = 'GraphName is required.'
    return
  }
  graphSaving.value = true
  graphStatus.value = ''
  try {
    const result = await workspace.saveGraphByName(name)
    graphNameInput.value = result.name || result.id
    graphStatus.value = `Graph saved: ${result.name || result.id}`
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  } finally {
    graphSaving.value = false
  }
}

async function deleteMobileGraph(graph: { id: string; name?: string; display_name?: string }) {
  const graphId = String(graph.id || '').trim()
  if (!graphId) return
  const name = String(graph.display_name || graph.name || graphId)
  const ok = window.confirm(`Delete graph "${name}"? This will remove the whole graph folder and cannot be undone.`)
  if (!ok) return
  graphStatus.value = ''
  try {
    await workspace.deleteGraphById(graphId)
    graphStatus.value = `Graph deleted: ${name}`
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

async function openCreateNode() {
  if (workspace.view.value !== 'nodes' || !workspace.selectedGraph.value) return
  try {
    await workspace.refreshEditorCatalog()
    createNodeOpen.value = true
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  }
}

async function createMobileNode(payload: { typeId: string; nodeName: string; fields: Record<string, unknown> }) {
  try {
    await workspace.createNode(payload.typeId, payload.nodeName, payload.fields)
    createNodeOpen.value = false
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  }
}

async function deleteMobileNode(node: MobileNode) {
  const nodeId = String(node.id || '').trim()
  if (!nodeId) return
  const ok = window.confirm(`Delete node "${nodeId}"?`)
  if (!ok) return
  try {
    await workspace.deleteNode(node)
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  }
}

async function clearMemory() {
  if (workspace.view.value !== 'chat' || !workspace.selectedNode.value) return
  const nodeId = String(workspace.selectedNode.value.id || '').trim()
  const ok = window.confirm(`Clear all memory for node "${nodeId}"?`)
  if (!ok) return
  await workspace.clearSelectedNodeMemory()
  await nextTick()
  scrollFeedToBottom()
}

function messageTextForActions(message: MessageEnvelope) {
  return extractMemoryMessageText(message)
}

async function deleteMobileMessage(message: MessageEnvelope) {
  const messageId = String((message as any)?.id || '').trim()
  if (!messageId) return
  const ok = window.confirm('Delete this conversation entry?')
  if (!ok) return
  try {
    await workspace.deleteSelectedNodeMessage(messageId)
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  }
}

async function onConfigSaved() {
  await Promise.all([workspace.refreshNodeConfigs(), workspace.refreshCurrent()]).catch((e: any) => {
    workspace.error.value = String(e?.message || e)
  })
}

async function restartWorkspace() {
  if (isRestarting.value) return
  isRestarting.value = true
  workspace.error.value = ''
  try {
    await restartServer()
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
    isRestarting.value = false
  }
}

function scrollFeedToBottom() {
  const el = feedRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

function isFeedNearBottom() {
  const el = feedRef.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight <= SCROLL_STICK_THRESHOLD
}

watch(messageSignature, (_next, previous) => {
  const shouldStick = previous == null || isFeedNearBottom()
  if (!shouldStick) return
  void nextTick(scrollFeedToBottom)
})

watch(liveMessage, (_next, previous) => {
  const shouldStick = previous == null || isFeedNearBottom()
  if (!shouldStick) return
  void nextTick(scrollFeedToBottom)
})

onMounted(() => {
  void workspace.loadPcs()
})
</script>

<template>
  <div class="mobile-shell">
    <header class="mobile-header">
      <button v-if="settingsOpen" class="icon-btn" type="button" aria-label="Back" @click="closeSettings">&lt;</button>
      <button v-else-if="workspace.view.value === 'graphs'" class="icon-btn" type="button" aria-label="返回 PC" @click="workspace.backToPcs">&lt;</button>
      <button v-else-if="workspace.view.value === 'nodes'" class="icon-btn" type="button" aria-label="返回 Graph" @click="workspace.backToGraphs">&lt;</button>
      <button v-else-if="workspace.view.value === 'chat'" class="icon-btn" type="button" aria-label="返回节点" @click="workspace.backToNodes">&lt;</button>
      <div v-else class="header-spacer"></div>
      <div class="header-title">{{ headerTitle }}</div>
      <div class="header-actions">
        <button v-if="!settingsOpen && workspace.view.value === 'graphs'" class="text-icon-btn" type="button" aria-label="Open settings" @click="openSettings">Settings</button>
        <button v-if="!settingsOpen && workspace.view.value === 'chat'" class="text-icon-btn danger" type="button" aria-label="Clear memory" @click="clearMemory">ClearMemory</button>
        <button v-if="!settingsOpen && workspace.view.value === 'chat'" class="text-icon-btn" type="button" aria-label="打开节点配置" @click="openConfig">配置</button>
        <button v-if="!settingsOpen" class="text-icon-btn restart-btn" type="button" :disabled="isRestarting" aria-label="Restart" @click="restartWorkspace">
          {{ isRestarting ? 'Restarting...' : 'Restart' }}
        </button>
      </div>
    </header>

    <main class="mobile-main">
      <SettingsPage
        v-if="settingsOpen"
        back-label="Back"
        @back="closeSettings"
        @providers-updated="workspace.refreshEditorCatalog"
      />
      <template v-else>
        <div v-if="workspace.error.value" class="mobile-error">{{ workspace.error.value }}</div>
        <div v-if="workspace.loading.value" class="loading-line">Loading...</div>

        <section v-if="workspace.view.value === 'pcs'" class="mobile-list">
        <button v-for="pc in workspace.pcs.value" :key="pc.id" class="list-row pc-row" type="button" @click="workspace.selectPc(pc)">
          <span class="row-main">{{ pc.name }}</span>
          <span class="row-sub">{{ pc.instance_count }} instance</span>
          <span class="row-arrow">&gt;</span>
        </button>
      </section>

      <section v-else-if="workspace.view.value === 'graphs'" class="mobile-list">
        <div v-for="instance in workspace.graphInstances.value" :key="instance.id" class="instance-group">
          <div class="instance-head">
            <span>{{ instance.name }}</span>
            <small>{{ instance.path }}</small>
          </div>
          <div v-for="graph in instance.graphs" :key="graph.id" class="graph-row-wrap">
            <button class="list-row graph-row" type="button" @click="workspace.selectGraph(graph)">
              <span>
                <span class="row-main">{{ graph.display_name }}</span>
                <span class="row-sub">{{ graph.updated_at || 'not saved yet' }}</span>
              </span>
              <span class="row-arrow">&gt;</span>
            </button>
            <button class="mobile-delete-btn" type="button" @click="deleteMobileGraph(graph)">Delete</button>
          </div>
        </div>
        <form class="graph-save-panel" @submit.prevent="saveMobileGraph">
          <label class="graph-name-field">
            <span>GraphName</span>
            <input v-model="graphNameInput" type="text" placeholder="NewGraph" />
          </label>
          <button class="primary-action-btn" type="submit" :disabled="graphSaving">
            {{ graphSaving ? 'Saving...' : 'SaveGraph' }}
          </button>
          <div v-if="graphStatus" class="graph-status">{{ graphStatus }}</div>
        </form>
      </section>

      <section v-else-if="workspace.view.value === 'nodes'" class="mobile-list node-list">
        <MobileNodeListItem
          v-for="node in workspace.nodes.value"
          :key="node.id"
          :node="node"
          @select="workspace.selectNode"
          @delete="deleteMobileNode"
        />
        <button class="add-node-btn" type="button" @click="openCreateNode">Add Node</button>
      </section>

        <section v-else class="chat-view">
        <div class="node-summary">
          <span class="node-status" :class="workspace.selectedNode.value ? nodeStateClass(workspace.selectedNode.value) : 'state-idle'"></span>
          <span>{{ workspace.selectedNode.value ? nodeStateLabel(workspace.selectedNode.value) : '' }}</span>
          <span v-if="workspace.selectedNode.value?.last_runtime_event" class="activity-text">
            {{ String(workspace.selectedNode.value.last_runtime_event.name || workspace.selectedNode.value.last_runtime_event.type || '') }}
          </span>
        </div>

        <div ref="feedRef" class="chat-feed">
          <div v-if="messages.length === 0 && !liveMessage" class="empty-chat">暂无消息</div>
          <template v-for="entry in feedEntries" :key="entry.key">
            <article v-if="entry.type === 'message'" class="bubble" :class="messageRoleClass(entry.message)">
              <div class="bubble-meta">{{ String(entry.message.role || 'assistant') }}</div>
              <MobileMessageText :message="entry.message" />
              <div v-if="messageTextForActions(entry.message)" class="mobile-message-actions">
                <button type="button" class="mobile-message-action save" @click="openSaveMessageDialog(messageTextForActions(entry.message))">Save</button>
                <button type="button" class="mobile-message-action copy" @click="copyMessageText(messageTextForActions(entry.message))">Copy</button>
                <button type="button" class="mobile-message-action delete" @click="deleteMobileMessage(entry.message)">Delete</button>
              </div>
            </article>
            <section v-else class="mobile-tool-group" :class="{ expanded: isToolGroupExpanded(entry.key) }">
              <button class="mobile-tool-group-head" type="button" @click="toggleToolGroup(entry.key)">
                <span class="mobile-tool-main-row">
                  <span class="mobile-tool-left">
                    <span class="mobile-tool-caret">{{ isToolGroupExpanded(entry.key) ? 'v' : '>' }}</span>
                    <span class="mobile-tool-role">Tool</span>
                    <span class="mobile-tool-count">{{ toolGroupLabel(entry) }}</span>
                  </span>
                  <span class="mobile-tool-time">{{ toolGroupTime(entry) }}</span>
                </span>
                <span v-if="lastToolInstruction(entry)" class="mobile-tool-instruction">{{ lastToolInstruction(entry) }}</span>
              </button>
              <div v-if="isToolGroupExpanded(entry.key)" class="mobile-tool-list">
                <div
                  v-for="(part, index) in toolGroupParts(entry)"
                  :key="`${entry.key}-${String(part.call_id || index)}`"
                  class="mobile-tool-row"
                >
                  <div class="mobile-tool-row-head">
                    <span class="mobile-tool-dot" :class="`status-${toolStatus(part)}`"></span>
                    <span class="mobile-tool-name">{{ toolName(part) }}</span>
                    <span v-if="toolDuration(part)" class="mobile-tool-duration">{{ toolDuration(part) }}</span>
                    <span class="mobile-tool-status">{{ toolStatus(part) }}</span>
                  </div>
                  <MemoryToolCallPart :part="part" />
                </div>
              </div>
            </section>
          </template>
          <MobileLiveMessage v-if="liveMessage" :text="liveMessage" />
        </div>

        <form class="composer" @submit.prevent="sendDraft">
          <div class="composer-tools">
            <button class="attach-btn" type="button" :disabled="uploadingFiles || workspace.sending.value" @click="openFilePicker">
              {{ uploadingFiles ? '上传中...' : '添加图片或附件' }}
            </button>
            <button v-if="attachments.length > 0" class="clear-attachments-btn" type="button" @click="clearAttachments">清空</button>
            <button
              class="goal-toggle-btn"
              type="button"
              :class="{ active: goalActive }"
              :title="goalTitle"
              :disabled="!goalEnabled || workspace.sending.value"
              @click="toggleGoal"
            >
              Goal
            </button>
            <input ref="fileInputRef" class="hidden-file-input" type="file" multiple @change="onFileSelected" />
          </div>
          <div v-if="attachments.length > 0" class="mobile-attachments">
            <span v-for="(file, index) in attachments" :key="file.path" class="mobile-attachment-chip">
              <span class="attachment-label">{{ file.name || file.path }}</span>
              <button type="button" aria-label="移除附件" @click="removeAttachment(index)">x</button>
            </span>
          </div>
          <div class="composer-row">
            <textarea v-model="draft" rows="2" placeholder="输入消息" :disabled="workspace.sending.value"></textarea>
            <button type="submit" :disabled="workspace.sending.value || (!draft.trim() && attachments.length === 0)">发送</button>
          </div>
        </form>
        </section>
      </template>
    </main>

    <MobileNodeConfigDialog
      :open="configOpen"
      :graph-id="workspace.selectedGraph.value?.id || 'default'"
      :node="workspace.selectedNode.value"
      :config="workspace.selectedConfig.value"
      :providers="workspace.providers.value"
      :available-tools="workspace.availableTools.value"
      @close="configOpen = false"
      @saved="onConfigSaved"
      @error="workspace.error.value = $event"
    />
    <MobileNodeCreateDialog
      :open="createNodeOpen"
      :node-types="workspace.availableNodeTypes.value"
      :providers="workspace.providers.value"
      :available-tools="workspace.availableTools.value"
      @close="createNodeOpen = false"
      @create="createMobileNode"
      @error="workspace.error.value = $event"
    />
    <MemorySaveDialog
      v-model:filename="saveDialogFilename"
      :open="saveDialogOpen"
      :target-dir="saveDialogTargetDir"
      :error="saveDialogError"
      :saving="saveDialogSaving"
      @confirm="confirmSaveMessageDialog"
      @cancel="cancelSaveMessageDialog"
    />
  </div>
</template>

<style scoped>
.mobile-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #08111f;
}

.mobile-header {
  height: 54px;
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(8, 17, 31, 0.95);
}

.header-title {
  min-width: 0;
  text-align: center;
  font-weight: 700;
  font-size: 15px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.icon-btn,
.text-icon-btn {
  height: 36px;
  padding: 0;
  border-radius: 8px;
  line-height: 1;
}

.icon-btn {
  width: 36px;
  font-size: 18px;
}

.text-icon-btn {
  min-width: 46px;
  padding: 0 10px;
  font-size: 13px;
}

.restart-btn {
  min-width: 74px;
  padding: 0 9px;
  border-color: rgba(245, 158, 11, 0.55);
  color: #fbbf24;
}

.restart-btn:disabled {
  cursor: default;
  opacity: 0.7;
}

.header-spacer {
  width: 36px;
}

.mobile-main {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px;
  overflow: hidden;
}

.mobile-list {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
  padding-bottom: 12px;
}

.node-list > * {
  flex: 0 0 auto;
}

.list-row {
  width: 100%;
  min-height: 72px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 12px;
  text-align: left;
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
}

.row-main,
.row-sub {
  min-width: 0;
  display: block;
}

.row-main {
  color: rgba(248, 250, 252, 0.96);
  font-weight: 700;
  font-size: 15px;
  overflow-wrap: anywhere;
}

.row-sub,
.instance-head small,
.activity-text {
  color: rgba(148, 163, 184, 0.92);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.row-arrow {
  color: rgba(125, 211, 252, 0.88);
  font-size: 24px;
}

.instance-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.graph-row-wrap {
  display: flex;
  align-items: stretch;
  gap: 8px;
}

.graph-row {
  flex: 1 1 auto;
  min-width: 0;
}

.mobile-delete-btn {
  flex: 0 0 68px;
  min-height: 54px;
  padding: 0 8px;
  border-radius: 8px;
  border-color: rgba(248, 113, 113, 0.45);
  background: rgba(127, 29, 29, 0.3);
  color: rgba(254, 226, 226, 0.96);
  font-size: 12px;
}

.graph-save-panel {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.58);
}

.graph-name-field {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: rgba(203, 213, 225, 0.92);
  font-size: 12px;
}

.graph-name-field input {
  min-height: 38px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  color: rgba(248, 250, 252, 0.96);
  background: rgba(15, 23, 42, 0.78);
}

.primary-action-btn,
.add-node-btn {
  min-height: 38px;
  border-radius: 8px;
  border-color: rgba(56, 189, 248, 0.48);
  background: rgba(14, 165, 233, 0.3);
  color: rgba(224, 242, 254, 0.96);
}

.primary-action-btn {
  align-self: end;
  min-width: 96px;
  padding: 0 12px;
}

.graph-status {
  grid-column: 1 / -1;
  color: rgba(148, 163, 184, 0.95);
  font-size: 12px;
}

.add-node-btn {
  flex: 0 0 auto;
  width: 100%;
  min-height: 46px;
  font-weight: 700;
}

.instance-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px 2px 0;
  color: rgba(226, 232, 240, 0.96);
  font-size: 13px;
  font-weight: 700;
}

.node-status {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.75);
}

.state-working {
  background: #22c55e;
}

.state-stop {
  background: #f87171;
}

.state-idle {
  background: #38bdf8;
}

.chat-view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.node-summary {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.58);
  font-size: 13px;
}

.chat-feed {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
  padding: 4px 2px;
}

.bubble {
  flex: 0 0 auto;
  min-width: 0;
  max-width: 88%;
  padding: 9px 11px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(15, 23, 42, 0.76);
}

.from-user {
  align-self: flex-end;
  background: rgba(14, 165, 233, 0.24);
}

.from-node,
.from-tool {
  align-self: flex-start;
}

.bubble.from-node {
  width: 100%;
  max-width: none;
}

.from-tool {
  background: rgba(129, 140, 248, 0.18);
}

.bubble-meta {
  margin-bottom: 4px;
  color: rgba(148, 163, 184, 0.92);
  font-size: 11px;
}

.mobile-message-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.mobile-message-action {
  min-height: 30px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: rgba(15, 23, 42, 0.74);
  color: rgba(226, 232, 240, 0.94);
  font-size: 12px;
}

.mobile-message-action.save {
  border-color: rgba(74, 222, 128, 0.4);
  color: rgba(187, 247, 208, 0.96);
}

.mobile-message-action.copy {
  border-color: rgba(125, 211, 252, 0.4);
  color: rgba(186, 230, 253, 0.96);
}

.mobile-message-action.delete {
  border-color: rgba(248, 113, 113, 0.45);
  color: rgba(254, 202, 202, 0.98);
  background: rgba(127, 29, 29, 0.28);
}

.mobile-tool-group {
  flex: 0 0 auto;
  min-width: 0;
  width: min(100%, 96%);
  align-self: flex-start;
  border: 1px solid rgba(244, 114, 182, 0.22);
  border-radius: 8px;
  background: rgba(129, 140, 248, 0.14);
  overflow: hidden;
}

.mobile-tool-group-head {
  width: 100%;
  min-height: 42px;
  border: 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 0;
  background: rgba(0, 0, 0, 0.18);
  color: rgba(248, 250, 252, 0.96);
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 5px;
  text-align: left;
}

.mobile-tool-main-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.mobile-tool-left {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.mobile-tool-caret {
  width: 12px;
  color: rgba(244, 114, 182, 0.95);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 11px;
}

.mobile-tool-role {
  color: rgba(248, 250, 252, 0.96);
  font-size: 12px;
  font-weight: 700;
}

.mobile-tool-count,
.mobile-tool-time,
.mobile-tool-instruction,
.mobile-tool-duration,
.mobile-tool-status {
  color: rgba(203, 213, 225, 0.8);
  font-size: 11px;
}

.mobile-tool-time {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-tool-instruction {
  display: -webkit-box;
  padding-left: 19px;
  overflow: hidden;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow-wrap: anywhere;
  line-height: 1.4;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  white-space: pre-wrap;
}

.mobile-tool-group.expanded .mobile-tool-instruction {
  display: block;
}

.mobile-tool-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 9px;
}

.mobile-tool-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.mobile-tool-row + .mobile-tool-row {
  padding-top: 8px;
  border-top: 1px solid rgba(244, 114, 182, 0.14);
}

.mobile-tool-row-head {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.mobile-tool-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  flex: 0 0 auto;
  background: rgba(125, 211, 252, 0.95);
}

.mobile-tool-dot.status-completed {
  background: rgba(52, 211, 153, 0.95);
}

.mobile-tool-dot.status-error,
.mobile-tool-dot.status-failed,
.mobile-tool-dot.status-timeout {
  background: rgba(248, 113, 113, 0.95);
}

.mobile-tool-name {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(248, 250, 252, 0.95);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 12px;
}

:deep(.mobile-tool-row .feed-tool-call) {
  width: 100%;
  min-width: 0;
  max-width: 100%;
}

.composer {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(148, 163, 184, 0.14);
}

.composer-tools,
.composer-row {
  display: flex;
  gap: 8px;
}

.composer-tools {
  align-items: center;
}

.composer-row {
  align-items: flex-end;
}

.hidden-file-input {
  display: none;
}

.attach-btn,
.goal-toggle-btn,
.clear-attachments-btn {
  min-height: 34px;
  border-radius: 8px;
  padding: 0 10px;
  font-size: 13px;
}

.attach-btn {
  order: 1;
}

.goal-toggle-btn {
  order: 2;
  border-color: rgba(125, 211, 252, 0.32);
  background: rgba(15, 23, 42, 0.78);
  color: rgba(203, 213, 225, 0.92);
}

.goal-toggle-btn.active {
  border-color: rgba(34, 197, 94, 0.62);
  background: rgba(22, 163, 74, 0.22);
  color: rgba(220, 252, 231, 0.98);
}

.goal-toggle-btn:disabled {
  cursor: default;
  opacity: 0.5;
}

.clear-attachments-btn {
  order: 3;
  border-color: rgba(248, 113, 113, 0.28);
  background: rgba(127, 29, 29, 0.28);
}

.mobile-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mobile-attachment-chip {
  max-width: 100%;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 7px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(15, 23, 42, 0.72);
  color: rgba(226, 232, 240, 0.96);
  font-size: 12px;
}

.attachment-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-attachment-chip button {
  width: 22px;
  height: 22px;
  padding: 0;
  border-radius: 6px;
}

.composer textarea {
  width: 100%;
  resize: none;
  min-height: 44px;
  max-height: 110px;
  padding: 9px 10px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  color: rgba(248, 250, 252, 0.96);
  background: rgba(15, 23, 42, 0.78);
  font-family: inherit;
  font-size: 14px;
}

.composer-row > button {
  width: 64px;
  height: 44px;
  flex: 0 0 auto;
}

.mobile-error,
.loading-line,
.empty-chat {
  flex: 0 0 auto;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
}

.mobile-error {
  margin-bottom: 10px;
  border: 1px solid rgba(248, 113, 113, 0.45);
  background: rgba(127, 29, 29, 0.32);
  color: rgba(254, 226, 226, 0.96);
}

.loading-line,
.empty-chat {
  color: rgba(148, 163, 184, 0.95);
}
</style>
