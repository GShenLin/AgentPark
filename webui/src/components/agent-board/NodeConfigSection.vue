<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import {
  controlChannelReceiver,
  getNodeTemplate,
  startChannelLogin,
  waitChannelLogin,
  type ChannelReceiverStatus,
  type NodeInstanceConfig,
  type ProviderInfo,
} from '../../api'
import { ASSET_FIELD_KEYS, mergeDroppedPaths, resolveDroppedPaths } from '../../composables/droppedPaths'
import { getSchemaFieldType, normalizeSchemaFieldValue } from '../../composables/nodeSchemaFields'
import { AgentBoardKey, type NodeCard } from './context'
import { withPersistedCapabilityState } from './capabilitySchemaState'
import { formatNodeConfigChangeSummary, normalizeApplyError } from './nodeApplySummary'
import NodeConfigFields from './NodeConfigFields.vue'

const injectedCtx = inject(AgentBoardKey, null)
if (!injectedCtx) {
  throw new Error('AgentBoard context not found')
}
const ctx = injectedCtx

const props = defineProps<{
  node: NodeCard
  config: NodeInstanceConfig | null
  providers: ProviderInfo[]
  availableTools: string[]
}>()

const emit = defineEmits<{
  error: [message: string]
}>()

const loading = ref(false)
const draftFields = ref<Record<string, any>>({})
const dirtyKeys = ref<Record<string, true>>({})
const applying = ref(false)
const templateSchema = ref<Record<string, any>>({})
const templateFields = ref<Record<string, any>>({})
const dropFieldKey = ref('')
const uploadingFieldKey = ref('')
const channelBusy = ref('')
const channelStatus = ref<ChannelReceiverStatus | null>(null)
const qrModalOpen = ref(false)
const qrCodeUrl = ref('')
const loginSessionKey = ref('')
const loginMessage = ref('')
const applySummary = ref('')
let templateRequestId = 0

const schema = computed(() => withPersistedCapabilityState(templateSchema.value, props.config))
const fieldKeys = computed(() => Object.keys(schema.value || {}))
const dirtyCount = computed(() => Object.keys(dirtyKeys.value || {}).length)
const isChannelReceiver = computed(() => String(props.node?.typeId || '').trim() === 'channel_receiver_node')
const channelRunning = computed(() => Boolean(channelStatus.value?.running))
const channelStatusText = computed(() => {
  if (channelStatus.value?.last_error) return String(channelStatus.value.last_error)
  if (channelStatus.value?.last_message_at) return `Last message: ${channelStatus.value.last_message_at}`
  if (channelStatus.value?.account_id) return `Account: ${channelStatus.value.account_id}`
  return 'Not started'
})
const canShowQrImage = computed(() => /^https?:\/\//i.test(qrCodeUrl.value) || /^data:image\//i.test(qrCodeUrl.value))

function showError(message: string) {
  emit('error', String(message || '').trim())
}

function getFieldType(key: string) {
  return getSchemaFieldType(schema.value, key)
}

function setField(key: string, value: any) {
  draftFields.value = { ...draftFields.value, [key]: value }
  applySummary.value = ''
  if (!dirtyKeys.value[key]) {
    dirtyKeys.value = { ...dirtyKeys.value, [key]: true }
  }
}

function resetDraftFromConfig() {
  const cfg = props.config as Record<string, any> | null
  const next: Record<string, any> = {}
  for (const key of fieldKeys.value) {
    next[key] = cfg?.[key] ?? templateFields.value[key]
  }
  draftFields.value = next
  dirtyKeys.value = {}
}

async function loadTemplate(typeId: string) {
  const safeTypeId = String(typeId || '').trim()
  templateRequestId += 1
  const requestId = templateRequestId
  if (!safeTypeId) {
    templateSchema.value = {}
    templateFields.value = {}
    return
  }
  try {
    const tpl = await getNodeTemplate(safeTypeId)
    if (requestId !== templateRequestId) return
    templateSchema.value = (tpl.schema || {}) as Record<string, any>
    templateFields.value = { ...(tpl.fields || {}) }
  } catch (e: any) {
    if (requestId !== templateRequestId) return
    templateSchema.value = {}
    templateFields.value = {}
    showError(String(e?.message || e))
  }
}

async function openForNode(nodeId: string) {
  const targetId = String(nodeId || '').trim()
  templateRequestId += 1
  if (!targetId) {
    draftFields.value = {}
    dirtyKeys.value = {}
    templateSchema.value = {}
    templateFields.value = {}
    applySummary.value = ''
    loading.value = false
    channelStatus.value = null
    qrModalOpen.value = false
    return
  }
  loading.value = true
  try {
    await ctx.refreshNodeConfig(targetId).catch(() => null)
    await loadTemplate(String(props.node?.typeId || '').trim())
    resetDraftFromConfig()
    if (String(props.node?.typeId || '').trim() === 'channel_receiver_node') {
      await refreshChannelStatus()
    } else {
      channelStatus.value = null
      qrModalOpen.value = false
    }
  } finally {
    loading.value = false
  }
}

async function applyChanges(): Promise<boolean> {
  const nodeId = props.node?.id
  if (!nodeId) return false
  const keys = Object.keys(dirtyKeys.value || {})
  if (!keys.length) return true

  const fields: Record<string, unknown> = {}
  for (const key of keys) {
    fields[key] = normalizeSchemaFieldValue(schema.value, key, draftFields.value[key])
  }

  applying.value = true
  showError('')
  applySummary.value = ''
  try {
    const result = await ctx.setNodeFields(nodeId, fields)
    await ctx.ensureNodeConfig(nodeId).catch(() => null)
    dirtyKeys.value = {}
    applySummary.value = formatNodeConfigChangeSummary(result)
    return true
  } catch (e: any) {
    showError(normalizeApplyError(e))
    return false
  } finally {
    applying.value = false
  }
}

function currentGraphId() {
  return String(ctx.currentGraphId.value || 'default').trim() || 'default'
}

function currentAccountId() {
  return String(draftFields.value.AccountId ?? props.config?.AccountId ?? '').trim()
}

async function refreshChannelStatus() {
  if (!isChannelReceiver.value || !props.node?.id) return
  channelBusy.value = 'status'
  showError('')
  try {
    channelStatus.value = await controlChannelReceiver(currentGraphId(), props.node.id, 'status')
  } catch (e: any) {
    showError(String(e?.message || e))
  } finally {
    if (channelBusy.value === 'status') channelBusy.value = ''
  }
}

async function startReceiver() {
  if (!props.node?.id) return
  if (dirtyCount.value > 0 && !(await applyChanges())) return
  channelBusy.value = 'start'
  showError('')
  try {
    channelStatus.value = await controlChannelReceiver(currentGraphId(), props.node.id, 'start')
    await ctx.ensureNodeConfig(props.node.id).catch(() => null)
  } catch (e: any) {
    showError(String(e?.message || e))
  } finally {
    if (channelBusy.value === 'start') channelBusy.value = ''
  }
}

async function stopReceiver() {
  if (!props.node?.id) return
  channelBusy.value = 'stop'
  showError('')
  try {
    channelStatus.value = await controlChannelReceiver(currentGraphId(), props.node.id, 'stop')
    await ctx.ensureNodeConfig(props.node.id).catch(() => null)
  } catch (e: any) {
    showError(String(e?.message || e))
  } finally {
    if (channelBusy.value === 'stop') channelBusy.value = ''
  }
}

async function openLoginQr() {
  if (!props.node?.id) return
  if (dirtyCount.value > 0 && !(await applyChanges())) return
  channelBusy.value = 'login-start'
  showError('')
  try {
    const res = await startChannelLogin(currentGraphId(), props.node.id, currentAccountId(), true)
    qrCodeUrl.value = String(res.qrcode_url || '').trim()
    loginSessionKey.value = String(res.session_key || '').trim()
    loginMessage.value = String(res.message || '')
    qrModalOpen.value = true
  } catch (e: any) {
    showError(String(e?.message || e))
  } finally {
    if (channelBusy.value === 'login-start') channelBusy.value = ''
  }
}

async function waitLogin() {
  if (!props.node?.id || !loginSessionKey.value) return
  channelBusy.value = 'login-wait'
  showError('')
  try {
    const res = await waitChannelLogin(currentGraphId(), props.node.id, loginSessionKey.value, 60)
    loginMessage.value = String(res.message || res.status || '')
    if (res.connected) {
      qrModalOpen.value = false
      await refreshChannelStatus()
      await ctx.ensureNodeConfig(props.node.id).catch(() => null)
    }
  } catch (e: any) {
    showError(String(e?.message || e))
  } finally {
    if (channelBusy.value === 'login-wait') channelBusy.value = ''
  }
}

function hasDroppedPayload(event: DragEvent) {
  const internal = String(event.dataTransfer?.getData('application/x-agentpark-file') || '').trim()
  if (internal) return true
  return Array.from(event.dataTransfer?.files || []).length > 0
}

function isAssetFieldKey(key: string) {
  return ASSET_FIELD_KEYS.has(String(key || '').trim())
}

function onFieldDragOver(key: string, event: DragEvent) {
  if (!hasDroppedPayload(event)) return
  event.preventDefault()
  if (!isAssetFieldKey(key)) return
  dropFieldKey.value = key
}

function onFieldDragLeave(key: string) {
  if (dropFieldKey.value === key) dropFieldKey.value = ''
}

async function onFieldDrop(key: string, event: DragEvent) {
  if (!hasDroppedPayload(event)) return
  event.preventDefault()
  if (!isAssetFieldKey(key)) return
  dropFieldKey.value = ''
  uploadingFieldKey.value = key
  try {
    const dropped = await resolveDroppedPaths(event, 'node-side-editor-field')
    if (!dropped.length) return
    setField(key, mergeDroppedPaths(getFieldType(key), draftFields.value[key], dropped))
  } catch (e: any) {
    showError(String(e?.message || e))
  } finally {
    uploadingFieldKey.value = ''
  }
}

watch(
  () => props.node.id,
  async (nodeId) => {
    await openForNode(String(nodeId || ''))
  },
  { immediate: true },
)

watch(
  () => props.config,
  () => {
    if (applying.value) return
    if (dirtyCount.value > 0) return
    resetDraftFromConfig()
  },
)
</script>

<template>
  <section class="editor-section config-section">
    <div class="section-head config-head">
      <div class="section-title">Config</div>
      <button class="apply-btn" :disabled="dirtyCount === 0 || applying" @click="applyChanges">
        {{ applying ? 'Applying...' : `Apply${dirtyCount > 0 ? ` (${dirtyCount})` : ''}` }}
      </button>
    </div>

    <div v-if="applySummary" class="apply-summary">{{ applySummary }}</div>

    <div v-if="loading" class="empty-hint">Loading node config...</div>
    <div v-else-if="fieldKeys.length === 0" class="empty-hint">This node has no editable fields.</div>

    <NodeConfigFields
      v-else
      class="field-list"
      :type-id="node.typeId"
      :schema="schema"
      :fields="draftFields"
      :providers="providers"
      :available-tools="availableTools"
      :drop-target-key="dropFieldKey"
      :uploading-key="uploadingFieldKey"
      :reset-key="node.id"
      enable-asset-drop
      enable-prompt-library
      @update-field="setField"
      @field-dragover="onFieldDragOver"
      @field-dragleave="onFieldDragLeave"
      @field-drop="onFieldDrop"
      @field-error="showError"
    />

    <div v-if="isChannelReceiver" class="channel-controls">
      <div class="channel-state">
        <span class="channel-state-label">Status</span>
        <span class="channel-status" :class="{ running: channelRunning }">
          {{ channelRunning ? 'Running' : 'Stopped' }}
        </span>
        <button class="mini-btn" type="button" :disabled="!!channelBusy" @click="refreshChannelStatus">
          {{ channelBusy === 'status' ? 'Checking...' : 'Status' }}
        </button>
      </div>
      <div class="channel-hint">{{ channelStatusText }}</div>
      <div class="channel-actions">
        <button class="mini-btn primary" type="button" :disabled="!!channelBusy" @click="openLoginQr">
          {{ channelBusy === 'login-start' ? 'Opening...' : 'Login QR' }}
        </button>
        <button v-if="!channelRunning" class="mini-btn" type="button" :disabled="!!channelBusy" @click="startReceiver">
          {{ channelBusy === 'start' ? 'Starting...' : 'Start' }}
        </button>
        <button v-else class="mini-btn danger" type="button" :disabled="!!channelBusy" @click="stopReceiver">
          {{ channelBusy === 'stop' ? 'Stopping...' : 'Stop' }}
        </button>
      </div>

      <div v-if="qrModalOpen" class="channel-login">
        <div class="login-copy">
          <div class="login-title">Weixin Login</div>
          <button class="mini-btn" type="button" @click="qrModalOpen = false">Hide</button>
        </div>
        <div class="qr-frame">
          <img v-if="canShowQrImage" class="qr-image" :src="qrCodeUrl" alt="Weixin login QR code" />
          <a v-else class="qr-link" :href="qrCodeUrl" target="_blank" rel="noreferrer">{{ qrCodeUrl }}</a>
        </div>
        <div v-if="loginMessage" class="qr-message">{{ loginMessage }}</div>
        <div class="qr-actions">
          <a class="mini-btn" :href="qrCodeUrl" target="_blank" rel="noreferrer">Open</a>
          <button class="mini-btn primary" type="button" :disabled="channelBusy === 'login-wait'" @click="waitLogin">
            {{ channelBusy === 'login-wait' ? 'Waiting...' : 'I scanned it' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.editor-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}

.config-section {
  flex: 1 1 auto;
  min-height: 0;
  justify-content: flex-start;
  overflow: auto;
  border-top: 1px solid rgba(148, 163, 184, 0.28);
  padding-top: 16px;
  padding-right: 4px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.config-head {
  position: sticky;
  top: 0;
  z-index: 5;
  padding-bottom: 8px;
  background: linear-gradient(180deg, #020617 0%, rgba(2, 6, 23, 0.92) 78%, rgba(2, 6, 23, 0) 100%);
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: #e2e8f0;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.empty-hint {
  font-size: 12px;
  color: rgba(148, 163, 184, 0.84);
}

.apply-summary {
  border: 1px solid rgba(45, 212, 191, 0.24);
  border-radius: 8px;
  background: rgba(15, 118, 110, 0.14);
  color: #ccfbf1;
  font-size: 12px;
  line-height: 1.35;
  overflow-wrap: anywhere;
  padding: 8px 10px;
}

.field-list {
  flex: 0 0 auto;
  gap: 12px;
}

.apply-btn {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.9);
  color: #f8fafc;
  cursor: pointer;
  position: relative;
  z-index: 2;
  padding: 6px 10px;
  font-size: 12px;
}

.channel-controls {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 0 0 auto;
  margin-top: 2px;
  border-top: 1px solid rgba(148, 163, 184, 0.2);
  padding-top: 12px;
}

.channel-state,
.channel-actions,
.login-copy,
.qr-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.channel-state-label,
.login-title {
  font-size: 12px;
  font-weight: 600;
  color: #cbd5e1;
}

.channel-status {
  margin-right: auto;
  font-size: 12px;
  color: #f97316;
}

.channel-status.running {
  color: #22c55e;
}

.channel-hint,
.qr-message {
  font-size: 12px;
  line-height: 1.45;
  color: rgba(203, 213, 225, 0.86);
  word-break: break-word;
}

.channel-hint {
  max-height: 72px;
  overflow: auto;
  padding-right: 2px;
}

.mini-btn,
.qr-actions .mini-btn {
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.92);
  color: #f8fafc;
  cursor: pointer;
  padding: 6px 9px;
  font-size: 12px;
  text-decoration: none;
  white-space: nowrap;
}

.mini-btn:disabled {
  cursor: default;
  opacity: 0.55;
}

.mini-btn.primary {
  background: rgba(37, 99, 235, 0.3);
  border-color: rgba(96, 165, 250, 0.45);
}

.mini-btn.danger {
  background: rgba(239, 68, 68, 0.18);
  border-color: rgba(248, 113, 113, 0.38);
}

.channel-login {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 2px;
  border-top: 1px solid rgba(148, 163, 184, 0.16);
  padding-top: 10px;
}

.qr-frame {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 154px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  background: #fff;
  padding: 10px;
}

.qr-image {
  width: 148px;
  max-width: 100%;
  aspect-ratio: 1 / 1;
  object-fit: contain;
}

.qr-link {
  color: #1d4ed8;
  font-size: 12px;
  line-height: 1.4;
  word-break: break-all;
}
</style>
