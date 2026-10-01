<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { type MessageEnvelope } from '../../api'
import { composeMessage } from '../../composables/messageAttachments'
import { useMessageAttachments } from '../../composables/useMessageAttachments'
import NodeVoiceCall from '../../voice/NodeVoiceCall.vue'
import { useGlobalState } from '../../composables/useGlobalState'
import DangerButton from '../DangerButton.vue'
import { AgentBoardKey } from './context'
import MessageComposer from '../MessageComposer.vue'
import ConversationComposerDock from '../ConversationComposerDock.vue'

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx = injected

const {
  lastError,
  nodeEditorInputText,
  nodeEditorAttachments,
  nodeEditorAttachmentDrafts,
  nodeTriggerInputs,
} = useGlobalState()

const attachments = useMessageAttachments({
  text: nodeEditorInputText, attachments: nodeEditorAttachments,
  context: () => `${ctx.currentGraphId.value}:${ctx.selectedNodeId.value}`,
  onError: message => { lastError.value = message },
})
const isUploadingFiles = attachments.isUploading
const sending = ref(false)
const voiceCall = ref<InstanceType<typeof NodeVoiceCall> | null>(null)
const goalArmedByNode = ref<Record<string, boolean>>({})

const selectedNode = computed(() => {
  const id = String(ctx.selectedNodeId.value || '').trim()
  if (!id) return null
  return ctx.nodes.value.find((item) => item.id === id) || null
})

const selectedConfig = computed(() => {
  const id = selectedNode.value?.id
  if (!id) return null
  return ctx.nodeConfigs.value[id] || null
})

const hasSelectedNode = computed(() => !!selectedNode.value)
const canSend = computed(() => hasSelectedNode.value)
const isNodeRunning = computed(() => (selectedNode.value ? ctx.isNodeRunning(selectedNode.value.id) : false))
const isStopRequested = computed(() => {
  const id = String(selectedNode.value?.id || '').trim()
  return !!(id && ctx.nodeConfigs.value[id]?._stop_requested)
})
const selectedGoalState = computed(() => {
  const state = selectedConfig.value?.goal_state
  return state && typeof state === 'object' ? state as Record<string, unknown> : null
})
const selectedGoalText = computed(() => String(selectedConfig.value?.goal || '').trim())
const hasPersistedGoal = computed(() => !!(selectedGoalText.value || selectedGoalState.value))
const isAgentNode = computed(() => selectedNode.value?.typeId === 'agent_node')
const audioInputEnabled = computed(() => isAgentNode.value)
const goalEnabled = computed(() => isAgentNode.value || hasPersistedGoal.value)
const goalActive = computed(() => {
  const id = String(selectedNode.value?.id || '').trim()
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

function resetEditorInput() {
  nodeEditorInputText.value = ''
  nodeEditorAttachments.value = []
}

function rememberEditorInput(nodeId: string | null | undefined) {
  const id = String(nodeId || '').trim()
  if (!id) return
  nodeTriggerInputs.value = {
    ...nodeTriggerInputs.value,
    [id]: String(nodeEditorInputText.value || ''),
  }
  nodeEditorAttachmentDrafts.value = {
    ...nodeEditorAttachmentDrafts.value,
    [id]: nodeEditorAttachments.value.map((attachment) => ({ ...attachment })),
  }
}

function loadEditorInput(nodeId: string | null | undefined) {
  const id = String(nodeId || '').trim()
  nodeEditorInputText.value = id ? String(nodeTriggerInputs.value[id] || '') : ''
  nodeEditorAttachments.value = id
    ? (nodeEditorAttachmentDrafts.value[id] || []).map((attachment) => ({ ...attachment }))
    : []
}

function composePayload() {
  return composeMessage(nodeEditorInputText.value, nodeEditorAttachments.value, 'node_editor')
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

async function persistGoalForSend(nodeId: string, payload: string | MessageEnvelope) {
  if (!goalActive.value || !isAgentNode.value) return
  const objective = payloadGoalText(payload)
  if (!objective) {
    throw new Error('Goal mode requires non-empty input.')
  }
  await ctx.setNodeFields(nodeId, {
    goal: objective,
    goal_state: {
      status: 'active',
      reason: 'Goal started from node input.',
      turn_count: 0,
      updated_at: new Date().toISOString(),
    },
  })
}

async function toggleGoal() {
  const nodeId = selectedNode.value?.id
  if (!nodeId) return
  if (!goalEnabled.value) return
  lastError.value = null
  try {
    if (goalActive.value) {
      goalArmedByNode.value = { ...goalArmedByNode.value, [nodeId]: false }
      await ctx.clearNodeFields(nodeId, ['goal', 'goal_state'])
    } else {
      goalArmedByNode.value = { ...goalArmedByNode.value, [nodeId]: true }
    }
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  }
}

async function sendMessage() {
  const nodeId = selectedNode.value?.id
  if (!nodeId || !canSend.value || sending.value || isUploadingFiles.value) return
  sending.value = true
  const payload = composePayload()
  lastError.value = null
  try {
    await persistGoalForSend(nodeId, payload)
    await ctx.sendNodeMessage(nodeId, payload)
    if (String(ctx.selectedNodeId.value || '') === nodeId) {
      resetEditorInput()
    }
    nodeTriggerInputs.value = { ...nodeTriggerInputs.value, [nodeId]: '' }
    nodeEditorAttachmentDrafts.value = { ...nodeEditorAttachmentDrafts.value, [nodeId]: [] }
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  } finally { sending.value = false }
}

watch(
  () => ctx.selectedNodeId.value,
  async (nodeId, prevNodeId) => {
    if (String(nodeId || '') === String(prevNodeId || '')) return
    rememberEditorInput(prevNodeId)
    loadEditorInput(nodeId)
  },
  { immediate: true },
)
</script>

<template>
  <ConversationComposerDock
    v-if="selectedNode"
    class="node-input-dock"
    @pointerdown.stop
    @click.stop
  >
    <template #status>
      <NodeVoiceCall v-if="audioInputEnabled" ref="voiceCall" :key="`${ctx.currentGraphId.value}:${selectedNode.id}:${ctx.memoryMode.value}`"
        :node-id="selectedNode.id" :graph-id="ctx.currentGraphId.value || 'default'"
      />
    </template>
    <MessageComposer
      v-model:input-text="nodeEditorInputText"
      :attachments="nodeEditorAttachments"
      :can-send="canSend"
      :disabled="sending"
      :is-uploading-files="isUploadingFiles"
      :goal-active="goalActive"
      :goal-enabled="goalEnabled"
      :goal-title="goalTitle"
      @drop-input="attachments.drop"
      @paste-input="attachments.paste"
      @remove-attachment="attachments.remove"
      @add-files="attachments.addFiles"
      @toggle-goal="toggleGoal"
      @send="sendMessage"
    >
      <template #actions>
        <button v-if="audioInputEnabled" class="record-btn" type="button" :disabled="sending || isUploadingFiles || voiceCall?.active"
          @click="voiceCall?.start()">{{ voiceCall?.active ? '通话中' : '语音通话' }}</button>
      </template>
    </MessageComposer>
    <DangerButton v-if="isNodeRunning" compact class="stop-btn" @click="ctx.stopNodeWork(selectedNode.id).catch(() => null)">
      {{ isStopRequested ? 'Stopping' : 'Stop' }}
    </DangerButton>
  </ConversationComposerDock>
</template>
