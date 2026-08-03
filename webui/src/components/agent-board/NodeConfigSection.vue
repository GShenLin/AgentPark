<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import {
  controlChannelReceiver,
  getNodeTemplate,
  loadAgentProfileIntoNode,
  startChannelLogin,
  waitChannelLogin,
  type ChannelReceiverStatus,
  type NodeInstanceConfig,
  type ProviderInfo,
} from '../../api'
import { ASSET_FIELD_KEYS, mergeDroppedPaths, resolveDroppedPaths } from '../../composables/droppedPaths'
import { getSchemaFieldType, normalizeSchemaFieldValue } from '../../composables/nodeSchemaFields'
import { resolveAgentProviderSchemaContext } from '../../composables/useAgentNodeCreateSchema'
import { waitForSelectionRequestWindow } from '../../selectionRequestPolicy'
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import { AgentBoardKey, type NodeCard } from './context'
import { withPersistedCapabilityState } from './capabilitySchemaState'
import { formatNodeConfigChangeSummary, normalizeApplyError } from './nodeApplySummary'
import NodeConfigFields from './NodeConfigFields.vue'
import NodeProfileLoadControl from './NodeProfileLoadControl.vue'
import NodeRuntimeEventsFieldGroup from './NodeRuntimeEventsFieldGroup.vue'
import { t } from '../../i18n'

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
const profileLoading = ref(false)
const runtimeEventsRevision = ref(0)
const templateSchema = ref<Record<string, any>>({})
const fieldSchemaCache = ref<Record<string, any>>({})
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
let loadedSchemaContextKey = ''
let openRequestId = 0
let openAbortController: AbortController | null = null

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

function resetDraftFromConfig(configOverride?: Record<string, any> | null) {
  const cfg = configOverride === undefined
    ? props.config as Record<string, any> | null
    : configOverride
  const next: Record<string, any> = {}
  for (const key of fieldKeys.value) {
    next[key] = cfg?.[key] ?? templateFields.value[key]
  }
  draftFields.value = next
  dirtyKeys.value = {}
}

function schemaContextKey(fields: Record<string, any> | null | undefined) {
  const context = resolveAgentProviderSchemaContext(props.providers, fields)
  return context.providerId
}

async function loadTemplate(
  typeId: string,
  contextFields: Record<string, any> | null | undefined = null,
  preserveDraft = false,
  signal?: AbortSignal,
) {
  const safeTypeId = String(typeId || '').trim()
  templateRequestId += 1
  const requestId = templateRequestId
  if (!safeTypeId) {
    templateSchema.value = {}
    fieldSchemaCache.value = {}
    templateFields.value = {}
    loadedSchemaContextKey = ''
    return
  }
  try {
    const contextKey = schemaContextKey(contextFields)
    const tpl = await getNodeTemplate(safeTypeId, { providerId: contextKey }, { signal })
    if (requestId !== templateRequestId) return
    const nextSchema = (tpl.schema || {}) as Record<string, any>
    templateSchema.value = nextSchema
    fieldSchemaCache.value = preserveDraft
      ? { ...fieldSchemaCache.value, ...nextSchema }
      : { ...nextSchema }
    templateFields.value = { ...(tpl.fields || {}) }
    loadedSchemaContextKey = contextKey
    if (preserveDraft) {
      const config = props.config as Record<string, any> | null
      const nextDraft = { ...draftFields.value }
      for (const key of Object.keys(nextSchema)) {
        if (nextDraft[key] !== undefined) continue
        nextDraft[key] = config?.[key] ?? templateFields.value[key]
      }
      draftFields.value = nextDraft
    }
  } catch (e: any) {
    if (signal?.aborted) return
    if (requestId !== templateRequestId) return
    templateSchema.value = {}
    fieldSchemaCache.value = {}
    templateFields.value = {}
    loadedSchemaContextKey = ''
    showError(String(e?.message || e))
  }
}

async function openForNode(nodeId: string) {
  const targetId = String(nodeId || '').trim()
  const requestId = ++openRequestId
  openAbortController?.abort()
  openAbortController = null
  templateRequestId += 1
  if (!targetId) {
    draftFields.value = {}
    dirtyKeys.value = {}
    templateSchema.value = {}
    fieldSchemaCache.value = {}
    templateFields.value = {}
    loadedSchemaContextKey = ''
    applySummary.value = ''
    loading.value = false
    channelStatus.value = null
    qrModalOpen.value = false
    return
  }
  const controller = new AbortController()
  openAbortController = controller
  loading.value = true
  try {
    if (!(await waitForSelectionRequestWindow(controller.signal))) return
    await Promise.all([
      ctx.refreshNodeConfig(targetId, { signal: controller.signal }).catch((error) => {
        if (controller.signal.aborted) return null
        showError(String(error?.message || error))
        return null
      }),
      loadTemplate(
        String(props.node?.typeId || '').trim(),
        props.config as Record<string, any> | null,
        false,
        controller.signal,
      ),
    ])
    if (controller.signal.aborted || requestId !== openRequestId) return
    resetDraftFromConfig()
    if (String(props.node?.typeId || '').trim() === 'channel_receiver_node') {
      await refreshChannelStatus()
    } else {
      channelStatus.value = null
      qrModalOpen.value = false
    }
  } finally {
    if (requestId === openRequestId) {
      loading.value = false
      if (openAbortController === controller) openAbortController = null
    }
  }
}

onBeforeUnmount(() => {
  openRequestId += 1
  openAbortController?.abort()
  openAbortController = null
})

async function applyChanges(): Promise<boolean> {
  const nodeId = props.node?.id
  if (!nodeId) return false
  const keys = Object.keys(dirtyKeys.value || {})
  if (!keys.length) return true

  const fields: Record<string, unknown> = {}
  for (const key of keys) {
    fields[key] = normalizeSchemaFieldValue(fieldSchemaCache.value, key, draftFields.value[key])
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

async function loadProfile(profileId: string) {
  const safeProfileId = String(profileId || '').trim()
  const nodeId = String(props.node?.id || '').trim()
  if (!safeProfileId || !nodeId || profileLoading.value) return
  if (dirtyCount.value > 0 && !window.confirm('加载 Profile 将替换当前尚未保存的修改，是否继续？')) return

  profileLoading.value = true
  showError('')
  applySummary.value = ''
  try {
    const result = await loadAgentProfileIntoNode(safeProfileId, {
      graph_id: currentGraphId(),
      node_id: nodeId,
    })
    await ctx.refreshNodeConfig(nodeId)
    await loadTemplate(String(props.node?.typeId || '').trim(), result.config.after, false)
    resetDraftFromConfig(result.config.after)
    runtimeEventsRevision.value += 1
    const eventWarnings = (result.event_rules.warnings || []).map((item) => String(item || '').trim()).filter(Boolean)
    const warningText = eventWarnings.length ? ` ${eventWarnings.slice(0, 2).join(' ')}` : ''
    applySummary.value = `Loaded Profile ${safeProfileId}. ${formatNodeConfigChangeSummary(result.config)}${warningText}`
  } catch (error) {
    showError(normalizeApplyError(error))
  } finally {
    profileLoading.value = false
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
    if (applying.value || profileLoading.value) return
    if (dirtyCount.value > 0) return
    resetDraftFromConfig()
  },
)

watch(
  () => schemaContextKey(draftFields.value),
  (contextKey) => {
    if (String(props.node?.typeId || '').trim() !== 'agent_node') return
    if (loading.value || !contextKey || contextKey === loadedSchemaContextKey) return
    void loadTemplate(String(props.node?.typeId || '').trim(), draftFields.value, true)
  },
)
</script>

<template>
  <section class="editor-section config-section">
    <div class="section-head config-head">
      <div class="config-title-actions">
        <div class="section-title">{{ t('common.config') }}</div>
        <NodeProfileLoadControl
          :node-type-id="node.typeId"
          :busy="profileLoading || applying"
          @load="loadProfile"
          @error="showError"
        />
      </div>
      <ActionButton variant="primary" compact :disabled="dirtyCount === 0 || applying || profileLoading" @click="applyChanges">
        {{ applying ? 'Applying...' : `Apply${dirtyCount > 0 ? ` (${dirtyCount})` : ''}` }}
      </ActionButton>
    </div>

    <div v-if="applySummary" class="apply-summary">{{ applySummary }}</div>

    <div v-if="loading" class="empty-hint">{{ t('board.loadingConfig') }}</div>
    <div v-else-if="fieldKeys.length === 0" class="empty-hint">{{ t('board.noEditableFields') }}</div>

    <NodeConfigFields
      v-if="!loading && fieldKeys.length > 0"
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
        <span class="channel-state-label">{{ t('board.status') }}</span>
        <span class="channel-status" :class="{ running: channelRunning }">
          {{ channelRunning ? 'Running' : 'Stopped' }}
        </span>
        <ActionButton compact :disabled="!!channelBusy" @click="refreshChannelStatus">
          {{ channelBusy === 'status' ? 'Checking...' : 'Status' }}
        </ActionButton>
      </div>
      <div class="channel-hint">{{ channelStatusText }}</div>
      <div class="channel-actions">
        <ActionButton variant="primary" compact :disabled="!!channelBusy" @click="openLoginQr">
          {{ channelBusy === 'login-start' ? 'Opening...' : 'Login QR' }}
        </ActionButton>
        <ActionButton v-if="!channelRunning" compact :disabled="!!channelBusy" @click="startReceiver">
          {{ channelBusy === 'start' ? 'Starting...' : 'Start' }}
        </ActionButton>
        <DangerButton v-else compact :disabled="!!channelBusy" @click="stopReceiver">
          {{ channelBusy === 'stop' ? 'Stopping...' : 'Stop' }}
        </DangerButton>
      </div>

      <div v-if="qrModalOpen" class="channel-login">
        <div class="login-copy">
          <div class="login-title">Weixin Login</div>
          <ActionButton compact @click="qrModalOpen = false">{{ t('board.hide') }}</ActionButton>
        </div>
        <div class="qr-frame">
          <img v-if="canShowQrImage" class="qr-image" :src="qrCodeUrl" alt="Weixin login QR code" />
          <a v-else class="qr-link" :href="qrCodeUrl" target="_blank" rel="noreferrer">{{ qrCodeUrl }}</a>
        </div>
        <div v-if="loginMessage" class="qr-message">{{ loginMessage }}</div>
        <div class="qr-actions">
          <a class="qr-open-link" :href="qrCodeUrl" target="_blank" rel="noreferrer">{{ t('board.open') }}</a>
          <ActionButton variant="primary" compact :disabled="channelBusy === 'login-wait'" @click="waitLogin">
            {{ channelBusy === 'login-wait' ? 'Waiting...' : 'I scanned it' }}
          </ActionButton>
        </div>
      </div>
    </div>

    <NodeRuntimeEventsFieldGroup
      :key="`${node.id}:${runtimeEventsRevision}`"
      :node="node"
      :graph-id="currentGraphId()"
      @error="showError"
    />
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
  border-top: 1px solid var(--theme-panel-node-side-editor-border-color, rgba(148, 163, 184, 0.28));
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

.config-title-actions {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--theme-panel-node-side-editor-text-primary, #e2e8f0);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.empty-hint {
  font-size: 12px;
  color: var(--theme-panel-node-side-editor-text-secondary, rgba(148, 163, 184, 0.84));
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

.qr-open-link {
  min-height: var(--ui-control-height-compact, 28px);
  display: inline-flex;
  align-items: center;
  box-sizing: border-box;
  border: 1px solid var(--ui-button-border);
  border-radius: var(--ui-control-radius);
  background: var(--ui-button-background);
  color: var(--ui-button-text);
  padding: 0 10px;
  font-size: 12px;
  text-decoration: none;
  white-space: nowrap;
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
