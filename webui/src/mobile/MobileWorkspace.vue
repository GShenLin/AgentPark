<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AccessStatus, MessageEnvelope, MobileGraph, MobileNode, ResourceKind } from '../api'
import { restartServer } from '../api'
import { cloudBoardRestart } from '../portal/restartContext'
import { cloudBoardSession } from '../portal/boardSession'
const restartConnectedServer = inject(cloudBoardRestart, restartServer)
import { uploadFiles, type UploadedFileItem } from '../uploadApi'
import MemorySaveDialog from '../components/MemorySaveDialog.vue'
import MemoryTurnGroup from '../components/MemoryTurnGroup.vue'
import { useMemoryTurnEntries } from '../components/memoryFeedTools'

import CliSessionPicker from '../components/CliSessionPicker.vue'
import AppErrorToast from '../components/AppErrorToast.vue'
import ActionButton from '../components/ActionButton.vue'
import DangerButton from '../components/DangerButton.vue'
import FormSelect from '../components/FormSelect.vue'
import FormTextInput from '../components/FormTextInput.vue'
import MobileMemoryMessageCard from './MobileMemoryMessageCard.vue'
import MobileLiveMessage from './MobileLiveMessage.vue'
import MobileNodeCreateDialog from './MobileNodeCreateDialog.vue'
import MobileNodeConfigDialog from './MobileNodeConfigDialog.vue'
import MobileNodeListItem from './MobileNodeListItem.vue'
import MobileGroups from './MobileGroups.vue'
import SettingsPage from '../components/SettingsPage.vue'
import { useMemoryMessageExport } from '../composables/useMemoryMessageExport'
import { recordDeletionUndo } from '../composables/useDeletionUndo'
import { useAudioRecorder } from '../composables/useAudioRecorder'
import { useWorkAlerts } from '../composables/useWorkAlerts'
import { useMobileWorkspace } from './useMobileWorkspace'
import { useMobileBoardLocation } from './useMobileBoardLocation'
import { useMobileChatScroll } from './useMobileChatScroll'
import { buildMessageSignature } from './mobileMessageRender'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import { t } from '../i18n'
import { isCloudBoard } from '../portal/environment'
import { downloadMarkdown } from './downloadMarkdown'

const props = defineProps<{ access: AccessStatus }>()
const cloudBoard = isCloudBoard()
const boardHomePath = cloudBoard ? window.location.pathname : ''
const workspace = useMobileWorkspace({ initialPcId: cloudBoard ? 'local' : undefined })
const boardLocation = useMobileBoardLocation(workspace, cloudBoard)
const boardSession = inject(cloudBoardSession, null)
const unregisterBoardSession = boardSession?.register({
  suspend: workspace.suspendConnection,
  async restore() {
    if (boardLocation.initialized.value) await workspace.resumeConnection()
    else {
      await boardLocation.initialize()
      if (!boardLocation.initialized.value) throw new Error(workspace.error.value || '无法恢复当前页面。')
    }
  },
  activate: workspace.activateConnection,
})
const { navigationRequest, completeWorkAlertNavigation } = useWorkAlerts()
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
const audioRecorder = useAudioRecorder()
const submittingDraft = ref(false)
const configOpen = ref(false)
const createNodeOpen = ref(false)
const settingsOpen = ref(false)
const isDeveloper = computed(() => props.access.is_developer === true)
const isRestarting = ref(false)
const graphNameInput = ref('')
const selectedGraphProfileId = ref('')
const graphStatus = ref('')
const graphSaving = ref(false)
const graphProfileCreating = ref(false)
const goalArmedByNode = ref<Record<string, boolean>>({})
const workspaceMounted = ref(false)

const headerTitle = computed(() => {
  if (settingsOpen.value) return t('common.settings')
  if (workspace.view.value === 'pcs') return t('mobile.selectPc')
  if (workspace.view.value === 'graphs') return workspace.selectedPc.value?.name || t('mobile.selectGraph')
  if (workspace.view.value === 'nodes') return workspace.selectedGraph.value?.display_name || t('mobile.selectNode')
  return workspace.selectedNode.value?.name || workspace.selectedNode.value?.id || t('mobile.nodeMessages')
})
const isNodeChatView = computed(() => workspace.view.value === 'chat')

function saveMessage(text: string) {
  if (cloudBoard) downloadMarkdown(text)
  else void openSaveMessageDialog(text)
}

const messages = computed(() => workspace.conversation.value?.messages || [])
const feedEntries = useMemoryTurnEntries(messages)
const liveMessage = computed(() => String(workspace.conversation.value?.live_message || ''))
const thinkingMessage = computed(() => String(workspace.conversation.value?.thinking_message || ''))
const activityMessage = computed(() => String(workspace.conversation.value?.activity_message || ''))
const activityBlocks = computed(() => workspace.conversation.value?.activity_blocks || [])
const messageSignature = computed(() => buildMessageSignature(messages.value))
const selectedGoalState = computed(() => {
  const state = workspace.selectedNode.value?.goal_state
  return state && typeof state === 'object' ? state as Record<string, unknown> : null
})
const selectedGoalText = computed(() => String(workspace.selectedNode.value?.goal || '').trim())
const hasPersistedGoal = computed(() => !!(selectedGoalText.value || selectedGoalState.value))
const isAgentNode = computed(() => workspace.selectedNode.value?.type_id === 'agent_node')
const audioInputEnabled = computed(() => isAgentNode.value)
const goalEnabled = computed(() => isAgentNode.value || hasPersistedGoal.value)
const goalActive = computed(() => {
  const id = String(workspace.selectedNode.value?.id || '').trim()
  return goalEnabled.value && (!!(id && goalArmedByNode.value[id]) || hasPersistedGoal.value)
})
const goalTitle = computed(() => {
  const status = String(selectedGoalState.value?.status || '').trim()
  const reason = String(selectedGoalState.value?.reason || '').trim()
  if (selectedGoalText.value) {
    return reason
      ? t('goal.statusReason', { status: status || 'set', reason })
      : t('goal.status', { status: status || 'set' })
  }
  if (!isAgentNode.value) return t('goal.availableAgentOnly')
  return goalActive.value ? t('goal.disable') : t('goal.enable')
})
const selectedNodeRunning = computed(() => {
  const node = workspace.selectedNode.value
  if (!node) return false
  const state = String(node.state || 'idle')
  const pendingCount = Number(node.pending_count ?? 0)
  return state === 'working' || pendingCount > 0 || !!node.has_inflight || !!node.stop_requested
})
const selectedNodeStopRequested = computed(() => !!workspace.selectedNode.value?.stop_requested)
const composerLocked = computed(() => submittingDraft.value || workspace.sending.value)
const canSendDraft = computed(() => !composerLocked.value && (!!draft.value.trim() || attachments.value.length > 0))

type DraftSnapshot = {
  text: string
  attachments: UploadedFileItem[]
}

function canDeleteGraph(graph: MobileGraph) {
  if (typeof graph.deletable === 'boolean') return graph.deletable
  return !graph.readonly
}

function canEditGraph(graph: MobileGraph | null) {
  if (!graph) return false
  if (typeof graph.editable === 'boolean') return graph.editable
  return !graph.readonly
}

async function sendDraft() {
  if (composerLocked.value) return
  const text = draft.value.trim()
  if (!text && attachments.value.length === 0) return
  const snapshot = takeDraftSnapshot()
  const payload = composeDraftPayload(text, snapshot.attachments)
  submittingDraft.value = true
  let sent = false
  try {
    await persistGoalForSend(payload)
    await workspace.sendMessage(payload)
    sent = true
    clearDraftComposer()
    await nextTick()
    scrollFeedToBottom()
  } catch (e: any) {
    if (!sent) restoreDraftSnapshot(snapshot)
    workspace.error.value = String(e?.message || e)
  } finally {
    submittingDraft.value = false
  }
}

function takeDraftSnapshot(): DraftSnapshot {
  return {
    text: draft.value,
    attachments: [...attachments.value],
  }
}

function restoreDraftSnapshot(snapshot: DraftSnapshot) {
  draft.value = snapshot.text
  attachments.value = [...snapshot.attachments]
}

function clearDraftComposer() {
  draft.value = ''
  attachments.value = []
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

async function toggleAudioRecording() {
  workspace.error.value = ''
  try {
    if (!audioRecorder.recording.value) {
      await audioRecorder.start()
      return
    }
    const file = await audioRecorder.stop()
    uploadingFiles.value = true
    const uploaded = await uploadFiles([file], 'mobile-audio-recording')
    for (const item of uploaded.files || []) {
      if (!attachments.value.some((existing) => existing.path === item.path)) attachments.value.push(item)
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

function composeDraftPayload(text: string, files: UploadedFileItem[]): string | MessageEnvelope {
  if (!files.length) return text
  const parts: MessageEnvelope['parts'] = []
  if (text) parts.push({ type: 'text', text })
  for (const file of files) {
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
  await workspace.setSelectedNodeFields(
    {
      goal: objective,
      goal_state: {
        status: 'active',
        reason: 'Goal started from mobile input.',
        turn_count: 0,
        updated_at: new Date().toISOString(),
      },
    },
    { emitEvent: false },
  )
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

async function stopSelectedNode() {
  if (!selectedNodeRunning.value) return
  try {
    await workspace.stopSelectedNodeWork()
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  }
}

async function openConfig() {
  if (!isDeveloper.value || workspace.view.value !== 'chat' || !workspace.selectedNode.value) return
  configOpen.value = true
  await Promise.all([
    workspace.refreshEditorCatalog(),
    workspace.refreshGraphConfig(),
    workspace.refreshSelectedNodeConfig(),
    workspace.refreshAgentProfiles(),
  ]).catch((e: any) => {
    workspace.error.value = String(e?.message || e)
  })
}

function openSettings() {
  if (!isDeveloper.value || workspace.view.value !== 'graphs') return
  settingsOpen.value = true
}

function closeSettings() {
  settingsOpen.value = false
}

async function saveMobileGraph() {
  const name = graphNameInput.value.trim()
  if (!name) {
    graphStatus.value = t('mobile.graphNameRequired')
    return
  }
  graphSaving.value = true
  graphStatus.value = ''
  try {
    const result = await workspace.saveGraphByName(name)
    graphNameInput.value = result.name || result.id
    graphStatus.value = t('mobile.graphSaved', { name: result.name || result.id })
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  } finally {
    graphSaving.value = false
  }
}

async function createMobileGraphFromProfile() {
  const profileId = String(selectedGraphProfileId.value || '').trim()
  if (!profileId) {
    graphStatus.value = t('mobile.selectGraphPreset')
    return
  }
  const profile = workspace.graphProfiles.value.find((item) => item.id === profileId)
  const defaultGraphId = String(profile?.graph?.id || profile?.id || '').trim()
  const targetGraphId = String(window.prompt(t('mobile.graphId'), defaultGraphId) || '').trim()
  if (!targetGraphId) return
  graphProfileCreating.value = true
  graphStatus.value = ''
  try {
    const result = await workspace.createGraphFromPreset(profileId, targetGraphId)
    graphNameInput.value = result.graph.name || result.graph.id
    const name = result.graph.name || result.graph.id
    graphStatus.value = result.selected
      ? t('mobile.graphCreated', { name })
      : t('mobile.graphCreatedRefresh', { name })
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  } finally {
    graphProfileCreating.value = false
  }
}

async function deleteMobileGraph(graph: { id: string; name?: string; display_name?: string }) {
  const graphId = String(graph.id || '').trim()
  if (!graphId) return
  const name = String(graph.display_name || graph.name || graphId)
  const ok = window.confirm(t('mobile.deleteGraphConfirm', { name }))
  if (!ok) return
  graphStatus.value = ''
  try {
    await workspace.deleteGraphById(graphId)
    graphStatus.value = t('mobile.graphDeleted', { name })
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

async function openCreateNode() {
  if (workspace.view.value !== 'nodes' || !workspace.selectedGraph.value) return
  try {
    await Promise.all([workspace.refreshEditorCatalog(), workspace.refreshAgentProfiles()])
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

async function createMobileNodeFromProfile(profileId: string) {
  try {
    await workspace.createNodeFromProfile(profileId)
    createNodeOpen.value = false
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  }
}

async function deleteMobileNode(node: MobileNode) {
  const nodeId = String(node.id || '').trim()
  if (!nodeId) return
  const ok = window.confirm(t('mobile.deleteNodeConfirm', { name: nodeId }))
  if (!ok) return
  try {
    await workspace.deleteNode(node)
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  }
}

async function triggerMobileNode(node: MobileNode) {
  try {
    await workspace.triggerNode(node)
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  }
}

async function duplicateMobileNode(node: MobileNode) {
  try {
    await workspace.copyNode(node)
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  }
}

async function onChooseCliSession(sessionId: string) {
  await workspace.chooseCliSession(sessionId)
  await nextTick()
  scrollFeedToBottom()
}

async function clearMemory() {
  if (workspace.view.value !== 'chat' || !workspace.selectedNode.value) return
  const nodeId = String(workspace.selectedNode.value.id || '').trim()
  const targetLabel = workspace.cliMemoryClearTargetLabel(nodeId)
  const ok = window.confirm(t('mobile.clearTargetConfirm', { target: targetLabel }))
  if (!ok) return
  await workspace.clearSelectedNodeMemory()
  await nextTick()
  scrollFeedToBottom()
}

async function deleteMobileMessages(target: MessageEnvelope | MessageEnvelope[] | { kind: 'turn'; userMessage: MessageEnvelope }) {
  if (!Array.isArray(target) && (target as any)?.kind === 'turn') {
    const userMessage = (target as { kind: 'turn'; userMessage: MessageEnvelope }).userMessage
    const userMessageId = String((userMessage as any)?.id || '').trim()
    if (!userMessageId) return
    const ok = window.confirm(t('mobile.deleteTurnConfirm'))
    if (!ok) return
    try {
      const result = await workspace.deleteSelectedNodeTurn(userMessageId)
      recordDeletionUndo(result.undo_token ? {
        token: result.undo_token,
        kind: 'delete_dialogue',
        label: t('mobile.conversationTurn'),
      } : null)
    } catch (e: any) {
      workspace.error.value = String(e?.message || e)
    }
    return
  }
  const messagesToDelete = Array.isArray(target) ? target : [target]
  const messageIds = Array.from(new Set(
    messagesToDelete.map((message) => String((message as any)?.id || '').trim()).filter(Boolean),
  ))
  if (messageIds.length === 0) return
  const label = messageIds.length === 1
    ? t('mobile.conversationEntry')
    : t('mobile.conversationEntries', { count: messageIds.length })
  const ok = window.confirm(t('mobile.deleteEntryConfirm', { label }))
  if (!ok) return
  try {
    const result = await workspace.deleteSelectedNodeMessages(messageIds)
    recordDeletionUndo(result.undo_token ? {
      token: result.undo_token,
      kind: 'delete_dialogue',
      label: messageIds.length === 1 ? 'conversation entry' : `${messageIds.length} conversation entries`,
    } : null)
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
  }
}

async function onConfigSaved() {
  await workspace.refreshCurrent().catch((e: any) => {
    workspace.error.value = String(e?.message || e)
  })
}

async function restartWorkspace() {
  if (isRestarting.value) return
  isRestarting.value = true
  workspace.error.value = ''
  try {
    await restartConnectedServer()
  } catch (e: any) {
    workspace.error.value = String(e?.message || e)
    isRestarting.value = false
  }
}

const { scrollToBottom: scrollFeedToBottom } = useMobileChatScroll(
  feedRef,
  () => workspace.view.value === 'chat'
    ? `${workspace.selectedPc.value?.id}:${workspace.selectedGraph.value?.id}:${workspace.selectedNode.value?.id}`
    : '',
  () => workspace.conversation.value !== null,
  [messageSignature, liveMessage, thinkingMessage, activityMessage, activityBlocks],
)

function consumeWorkAlertNavigation(request: { graphId: string; nodeId: string; nonce: number }) {
  settingsOpen.value = false
  void workspace.openGraphNode(request.graphId, request.nodeId)
    .catch((error: unknown) => {
      workspace.error.value = String((error as { message?: unknown })?.message || error)
    })
    .finally(() => completeWorkAlertNavigation(request.nonce))
}

watch(
  navigationRequest,
  (request) => {
    if (!request || !workspaceMounted.value) return
    consumeWorkAlertNavigation(request)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  unregisterBoardSession?.()
  workspaceMounted.value = false
})

onMounted(async () => {
  await boardLocation.initialize()
  workspaceMounted.value = true
  if (navigationRequest.value) consumeWorkAlertNavigation(navigationRequest.value)
})
</script>

<template>
  <div v-if="boardLocation.restoring.value" class="mobile-shell restoring-chat" role="status">正在恢复当前页面…</div>
  <div v-else-if="!boardLocation.initialized.value && workspace.error.value" class="mobile-shell restoring-chat" role="alert">
    <p>{{ workspace.error.value }}</p>
    <button type="button" @click="boardLocation.initialize">重试</button>
    <a v-if="cloudBoard" :href="boardHomePath">返回 Board 列表</a>
  </div>
  <div v-else class="mobile-shell" :class="{ 'chat-appearance': isNodeChatView && !settingsOpen }">
    <header class="mobile-header">
      <button v-if="settingsOpen" class="icon-btn" type="button" :aria-label="t('common.back')" @click="closeSettings">&lt;</button>
      <button v-else-if="!cloudBoard && workspace.view.value === 'graphs'" class="icon-btn" type="button" :aria-label="t('mobile.backToPc')" @click="workspace.backToPcs">&lt;</button>
      <button v-else-if="workspace.view.value === 'nodes'" class="icon-btn" type="button" :aria-label="t('mobile.backToGraph')" @click="workspace.backToGraphs">&lt;</button>
      <button v-else-if="workspace.view.value === 'chat'" class="icon-btn" type="button" :aria-label="t('mobile.backToNodes')" @click="workspace.backToNodes">&lt;</button>
      <div v-else class="header-spacer"></div>
      <div class="header-title">{{ headerTitle }}</div>
      <div class="header-actions">
        <button v-if="isDeveloper && !settingsOpen && workspace.view.value === 'graphs'" class="text-icon-btn" type="button" :aria-label="t('mobile.openSettings')" @click="openSettings">{{ t('common.settings') }}</button>
        <LanguageSwitcher v-if="!isNodeChatView" compact />
        <DangerButton v-if="!settingsOpen && workspace.view.value === 'chat' && !workspace.selectedNode.value?.readonly" :aria-label="t('mobile.clearMemory')" @click="clearMemory">{{ t('mobile.clearMemory') }}</DangerButton>
        <button v-if="isDeveloper && !settingsOpen && workspace.view.value === 'chat' && !workspace.selectedNode.value?.readonly" class="text-icon-btn" type="button" :aria-label="t('mobile.openNodeConfig')" @click="openConfig">{{ t('common.config') }}</button>
        <button v-if="!settingsOpen && !isNodeChatView" class="text-icon-btn restart-btn" type="button" :disabled="isRestarting" :aria-label="t('common.restart')" @click="restartWorkspace">
          {{ isRestarting ? t('common.restarting') : t('common.restart') }}
        </button>
      </div>
    </header>

    <main class="mobile-main">
      <SettingsPage
        v-if="settingsOpen"
        :back-label="t('common.back')"
        @back="closeSettings"
        @providers-updated="workspace.refreshEditorCatalog"
      />
      <template v-else>
        <AppErrorToast
          :message="workspace.error.value"
          placement="mobile"
          @dismiss="workspace.error.value = ''"
        />
        <div v-if="workspace.loading.value" class="loading-line" role="status" aria-live="polite">{{ t('common.loading') }}</div>

        <section v-if="workspace.view.value === 'pcs'" class="mobile-list">
        <button v-for="pc in workspace.pcs.value" :key="pc.id" class="list-row pc-row" type="button" @click="workspace.selectPc(pc)">
          <span class="row-main">{{ pc.name }}</span>
          <span class="row-sub">{{ t('mobile.instanceCount', { count: pc.instance_count }) }}</span>
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
                <span class="row-sub">{{ graph.updated_at || t('mobile.notSavedYet') }}</span>
              </span>
              <span class="row-arrow">&gt;</span>
            </button>
            <DangerButton v-if="canDeleteGraph(graph)" @click="deleteMobileGraph(graph)">{{ t('common.delete') }}</DangerButton>
            <MobileGroups :key="`${workspace.selectedPc.value?.id}:${graph.id}`" :graph-id="graph.id" :pc-id="workspace.selectedPc.value?.id || 'local'" />
          </div>
        </div>
        <form class="graph-save-panel" @submit.prevent="saveMobileGraph">
          <label class="graph-name-field">
            <span>{{ t('mobile.graphName') }}</span>
            <FormTextInput v-model="graphNameInput" :placeholder="t('mobile.newGraph')" />
          </label>
          <ActionButton variant="primary" type="submit" :disabled="graphSaving">
            {{ graphSaving ? t('common.saving') : t('mobile.saveGraph') }}
          </ActionButton>
          <div v-if="graphStatus" class="graph-status">{{ graphStatus }}</div>
        </form>
        <section v-if="workspace.graphProfiles.value.length" class="graph-preset-panel">
          <label class="graph-name-field">
            <span>{{ t('mobile.graphPreset') }}</span>
            <FormSelect v-model="selectedGraphProfileId">
              <option value="">{{ t('mobile.profile') }}</option>
              <option v-for="profile in workspace.graphProfiles.value" :key="profile.id" :value="profile.id">
                {{ profile.name || profile.id }}
              </option>
            </FormSelect>
          </label>
          <ActionButton
            variant="primary"
            :disabled="!selectedGraphProfileId || graphProfileCreating"
            @click="createMobileGraphFromProfile"
          >
            {{ graphProfileCreating ? t('common.creating') : t('mobile.createFromProfile') }}
          </ActionButton>
        </section>
      </section>

      <section v-else-if="workspace.view.value === 'nodes'" class="mobile-list node-list">
        <MobileGroups v-if="workspace.selectedGraph.value && workspace.selectedPc.value" :graph-id="workspace.selectedGraph.value.id" :pc-id="workspace.selectedPc.value.id" />
        <MobileNodeListItem
          v-for="node in workspace.nodes.value"
          :key="node.id"
          :node="node"
          @select="workspace.selectNode"
          @delete="deleteMobileNode"
          @trigger="triggerMobileNode"
          @duplicate="duplicateMobileNode"
        />
        <ActionButton v-if="canEditGraph(workspace.selectedGraph.value)" variant="primary" block class="add-node-btn" @click="openCreateNode">{{ t('mobile.addNode') }}</ActionButton>
      </section>

      <section v-else class="chat-view">
        <CliSessionPicker
          v-if="workspace.cliSessionState.value?.supported"
          :sessions="workspace.cliSessionState.value.sessions"
          :session-label="workspace.cliSessionState.value.session_label"
          :active-session-id="workspace.cliSessionState.value.active_session_id"
          :is-new-session="workspace.cliSessionState.value.is_new_session"
          :loading="workspace.cliSessionLoading.value"
          @select="onChooseCliSession"
          @refresh="workspace.refreshCliSessions"
        />
        <div ref="feedRef" class="chat-feed">
          <div v-if="messages.length === 0 && !liveMessage && !thinkingMessage && !activityMessage && activityBlocks.length === 0" class="empty-chat">{{ t('mobile.emptyChat') }}</div>
          <template v-for="entry in feedEntries" :key="`${workspace.selectedPc.value?.id}:${workspace.selectedGraph.value?.id}:${workspace.selectedNode.value?.id}:${entry.key}`">
            <MobileMemoryMessageCard
              v-if="entry.type === 'message'"
              :message="entry.message"
              @save="saveMessage"
              @copy="copyMessageText"
              @delete="deleteMobileMessages"
            />
            <MemoryTurnGroup
              v-else
              :entry="entry"
              :load-turn-details="workspace.loadTurnDetails"
              :markdown-preview="true"
              compact
              @save="saveMessage"
              @copy="copyMessageText"
              @delete="deleteMobileMessages"
            />
          </template>
          <MobileLiveMessage
            v-if="liveMessage || thinkingMessage || activityMessage || activityBlocks.length"
            :key="`${workspace.selectedPc.value?.id}:${workspace.selectedGraph.value?.id}:${workspace.selectedNode.value?.id}:live`"
            :text="liveMessage"
            :thinking-text="thinkingMessage"
            :activity-text="activityMessage"
            :activity-blocks="activityBlocks"
            :node-id="workspace.selectedNode.value?.id"
            :graph-id="workspace.selectedGraph.value?.id"
          />
        </div>

        <form class="composer" @submit.prevent="sendDraft">
          <div class="composer-tools">
            <ActionButton class="attach-btn" compact :disabled="uploadingFiles || composerLocked" @click="openFilePicker">
              {{ uploadingFiles ? t('mobile.uploading') : t('mobile.addAttachment') }}
            </ActionButton>
            <DangerButton v-if="attachments.length > 0" class="clear-attachments-btn" compact :disabled="composerLocked" @click="clearAttachments">{{ t('mobile.clearAttachments') }}</DangerButton>
            <button
              v-if="audioInputEnabled"
              class="audio-record-btn"
              :class="{ active: audioRecorder.recording.value }"
              type="button"
              :disabled="!audioRecorder.supported.value || uploadingFiles || composerLocked"
              @click="toggleAudioRecording"
            >
              {{ audioRecorder.recording.value ? t('mobile.stopRecording') : t('mobile.startRecording') }}
            </button>
            <button
              v-if="!workspace.selectedNode.value?.readonly"
              class="goal-toggle-btn"
              type="button"
              :class="{ active: goalActive }"
              :title="goalTitle"
              :disabled="!goalEnabled || composerLocked"
              @click="toggleGoal"
            >
              Goal
            </button>
            <DangerButton
              v-if="selectedNodeRunning"
              class="stop-node-btn"
              compact
              :disabled="selectedNodeStopRequested"
              :title="selectedNodeStopRequested ? t('mobile.stopRequested') : t('mobile.stopCurrentWork')"
              @click="stopSelectedNode"
            >
              {{ selectedNodeStopRequested ? t('common.stopping') : t('common.stop') }}
            </DangerButton>
            <input ref="fileInputRef" class="hidden-file-input" type="file" multiple @change="onFileSelected" />
          </div>
          <div v-if="attachments.length > 0" class="mobile-attachments">
            <span v-for="(file, index) in attachments" :key="file.path" class="mobile-attachment-chip">
              <span class="attachment-label">{{ file.name || file.path }}</span>
              <DangerButton icon compact :disabled="composerLocked" :aria-label="t('mobile.removeAttachment')" @click="removeAttachment(index)">×</DangerButton>
            </span>
          </div>
          <div class="composer-row">
            <textarea v-model="draft" rows="2" :placeholder="t('mobile.messagePlaceholder')" :disabled="composerLocked"></textarea>
            <ActionButton variant="primary" type="submit" :disabled="!canSendDraft">{{ composerLocked ? t('mobile.sending') : t('mobile.send') }}</ActionButton>
          </div>
        </form>
        </section>
      </template>
    </main>

    <MobileNodeConfigDialog
      :open="configOpen"
      :node="workspace.selectedNode.value"
      :config="workspace.selectedConfig.value"
      :providers="workspace.providers.value"
      :available-tools="workspace.availableTools.value"
      :agent-profiles="workspace.agentProfiles.value"
      :graph-id="workspace.selectedGraph.value?.id || ''"
      :nodes="workspace.nodes.value"
      :output-routes="workspace.selectedNodeOutputRoutes.value"
      :save-fields="workspace.setSelectedNodeFields"
      :save-note="workspace.setSelectedNodeNote"
      :rename-node="workspace.renameSelectedNode"
      :save-profile="workspace.saveSelectedNodeProfile"
      :load-profile="workspace.loadSelectedNodeProfile"
      :add-output-route="workspace.addSelectedNodeOutputRoute"
      :update-output-route="workspace.updateSelectedNodeOutputRoute"
      :remove-output-route="workspace.removeSelectedNodeOutputRoute"
      @close="configOpen = false"
      @saved="onConfigSaved"
      @error="workspace.error.value = $event"
    />
    <MobileNodeCreateDialog
      :open="createNodeOpen"
      :node-types="workspace.availableNodeTypes.value"
      :agent-profiles="workspace.agentProfiles.value"
      :providers="workspace.providers.value"
      :available-tools="workspace.availableTools.value"
      @close="createNodeOpen = false"
      @create="createMobileNode"
      @create-profile="createMobileNodeFromProfile"
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
.restoring-chat { align-items: center; justify-content: center; gap: 16px; padding: 24px; color: #eaf1f4; }
.mobile-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  flex: 1;
  overflow: hidden;
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
  position: relative;
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
  flex-wrap: wrap;
  display: flex;
  align-items: stretch;
  gap: 8px;
}

.graph-row {
  flex: 1 1 auto;
  min-width: 0;
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

.graph-preset-panel {
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

.add-node-btn {
  flex: 0 0 auto;
  min-height: 46px;
  font-weight: 700;
}

.graph-status {
  grid-column: 1 / -1;
  color: rgba(148, 163, 184, 0.95);
  font-size: 12px;
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

.chat-view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chat-view :deep(.codex-session-picker) {
  flex: 0 0 auto;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 10px;
  background: rgba(8, 15, 29, 0.72);
  overflow: visible;
}

.chat-view :deep(.codex-session-menu) {
  left: 0;
  right: 0;
  z-index: 20;
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
  flex-wrap: wrap;
}

.composer-row {
  align-items: flex-end;
}

.hidden-file-input {
  display: none;
}

.attach-btn,
.goal-toggle-btn,
.stop-node-btn {
  min-height: 34px;
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

.goal-toggle-btn:disabled,
.stop-node-btn:disabled {
  cursor: default;
  opacity: 0.5;
}

.stop-node-btn {
  order: 3;
}

.clear-attachments-btn {
  order: 4;
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

.loading-line,
.empty-chat {
  flex: 0 0 auto;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
}

.loading-line,
.empty-chat {
  color: rgba(148, 163, 184, 0.95);
}

.loading-line {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 20;
  pointer-events: none;
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: rgba(15, 23, 42, 0.92);
  box-shadow: 0 8px 24px rgba(2, 6, 23, 0.28);
}

.graph-row-wrap > :deep(.mobile-groups) { flex: 0 0 100%; min-width: 0; }
</style>
