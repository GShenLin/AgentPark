<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  getNodeTemplate,
  type AgentProfile,
  type AgentProfileLoadResponse,
  type MobileNode,
  type NodeInstanceConfig,
  type ProviderInfo,
} from '../api'
import { normalizeSchemaFieldValue } from '../composables/nodeSchemaFields'
import { HARNESS_NODE_TYPES } from '../composables/useAgentNodeCreateSchema'
import ActionButton from '../components/ActionButton.vue'
import NodeConfigFields from '../components/agent-board/NodeConfigFields.vue'
import DangerButton from '../components/DangerButton.vue'
import DialogCloseButton from '../components/DialogCloseButton.vue'
import ExpandableTextarea from '../components/ExpandableTextarea.vue'
import FormSelect from '../components/FormSelect.vue'
import FormTextInput from '../components/FormTextInput.vue'
import { t } from '../i18n'
import MobileNodeProfilePickerSheet from './MobileNodeProfilePickerSheet.vue'
import NodeRuntimeEventsFieldGroup from '../components/agent-board/NodeRuntimeEventsFieldGroup.vue'
import type { MobileOutputRouteRow } from './useMobileWorkspace'
import {
  mobileNodeTemplateRequestKey,
  resolveMobileNodeTemplateProviderId,
} from './mobileNodeTemplateContext'

const props = defineProps<{
  open: boolean
  node: MobileNode | null
  config: NodeInstanceConfig | null
  providers: ProviderInfo[]
  availableTools: string[]
  agentProfiles: AgentProfile[]
  graphId: string
  nodes: MobileNode[]
  outputRoutes: MobileOutputRouteRow[]
  saveFields: (fields: Record<string, unknown>) => Promise<void>
  saveNote: (note: string) => Promise<void>
  renameNode: (name: string) => Promise<void>
  saveProfile: (profileId: string, profileName: string) => Promise<unknown>
  loadProfile: (profileId: string) => Promise<AgentProfileLoadResponse>
  addOutputRoute: () => Promise<void>
  updateOutputRoute: (
    routeId: string,
    patch: { outputIndex?: number; targetNodeId?: string; inputIndex?: number },
  ) => Promise<void>
  removeOutputRoute: (routeId: string) => Promise<void>
}>()

const emit = defineEmits<{
  close: []
  saved: []
  error: [message: string]
}>()

const loading = ref(false)
const saving = ref(false)
const profileSaving = ref(false)
const profileSaved = ref(false)
const profilePickerOpen = ref(false)
const runtimeEventsRevision = ref(0)
const templateSchema = ref<Record<string, any>>({})
const fieldSchemaCache = ref<Record<string, any>>({})
const templateFields = ref<Record<string, any>>({})
const draftFields = ref<Record<string, any>>({})
const dirtyKeys = ref<Record<string, true>>({})
const nodeNameDraft = ref('')
const nodeNameTouched = ref(false)
const noteDraft = ref('')
const noteTouched = ref(false)
const routing = ref(false)
let templateRequestId = 0
let profileSavedTimer: number | null = null
let loadedSchemaContextKey = ''

const schema = computed(() => templateSchema.value)
const fieldKeys = computed(() => Object.keys(schema.value || {}))
const currentNodeName = computed(() => String(props.node?.name || props.node?.id || '').trim())
const nodeNameDirty = computed(() => nodeNameTouched.value && nodeNameDraft.value.trim() !== currentNodeName.value)
const currentNote = computed(() => String(props.node?.note || '').trim())
const noteDirty = computed(() => noteTouched.value && noteDraft.value.trim() !== currentNote.value)
const dirtyCount = computed(() => (
  Object.keys(dirtyKeys.value || {}).length
  + (nodeNameDirty.value ? 1 : 0)
  + (noteDirty.value ? 1 : 0)
))
const canSave = computed(() => dirtyCount.value > 0 && !loading.value && !saving.value && (!nodeNameDirty.value || !!nodeNameDraft.value.trim()))
const templateKey = computed(() => {
  return mobileNodeTemplateRequestKey(
    props.open,
    props.node,
    props.config as Record<string, unknown> | null,
    props.providers,
  )
})
const targetNodes = computed(() => {
  const sourceNodeId = String(props.node?.id || '').trim()
  return (props.nodes || []).filter((item) => String(item.id || '').trim() && item.id !== sourceNodeId)
})
const canAddRoute = computed(() => !!props.node && targetNodes.value.length > 0 && !routing.value)
const availableProfiles = computed(() => {
  return (props.agentProfiles || [])
    .slice()
    .sort((left, right) => String(left.name || left.id).localeCompare(String(right.name || right.id)))
})

function showError(value: unknown) {
  emit('error', String((value as { message?: unknown })?.message || value || '').trim())
}

function setField(key: string, value: any) {
  draftFields.value = { ...draftFields.value, [key]: value }
  if (!dirtyKeys.value[key]) {
    dirtyKeys.value = { ...dirtyKeys.value, [key]: true }
  }
}

function setNodeName(value: string) {
  nodeNameDraft.value = value
  nodeNameTouched.value = true
}

function setNote(value: string) {
  noteDraft.value = value
  noteTouched.value = true
}

function portOptions(count: unknown) {
  const parsed = Number(count)
  const safeCount = Number.isFinite(parsed) ? Math.max(1, Math.floor(parsed)) : 1
  return Array.from({ length: safeCount }, (_, index) => index)
}

function inputOptions(nodeId: string) {
  const target = targetNodes.value.find((item) => item.id === nodeId)
  return portOptions(target?.input_num || 1)
}

function targetName(nodeId: string) {
  const target = targetNodes.value.find((item) => item.id === nodeId)
  return String(target?.name || nodeId)
}

async function runRouteChange(task: () => Promise<void>) {
  routing.value = true
  try {
    await task()
  } catch (e) {
    showError(e)
  } finally {
    routing.value = false
  }
}

function addRoute() {
  void runRouteChange(props.addOutputRoute)
}

function setRouteOutput(routeId: string, value: string) {
  void runRouteChange(() => props.updateOutputRoute(routeId, { outputIndex: Number(value) }))
}

function setRouteTarget(routeId: string, value: string) {
  void runRouteChange(() => props.updateOutputRoute(routeId, { targetNodeId: value, inputIndex: 0 }))
}

function setRouteInput(routeId: string, value: string) {
  void runRouteChange(() => props.updateOutputRoute(routeId, { inputIndex: Number(value) }))
}

function removeRoute(routeId: string) {
  void runRouteChange(() => props.removeOutputRoute(routeId))
}

function resetDraftFromConfig(config: Record<string, unknown> | null = props.config) {
  const cfg = config as Record<string, any> | null
  const next: Record<string, any> = {}
  for (const key of fieldKeys.value) {
    next[key] = cfg?.[key] ?? templateFields.value[key]
  }
  draftFields.value = next
  dirtyKeys.value = {}
}

function resetNodeNameDraft() {
  nodeNameDraft.value = currentNodeName.value
  nodeNameTouched.value = false
}

function resetNoteDraft() {
  noteDraft.value = String(props.node?.note || '')
  noteTouched.value = false
}

function schemaContextKey(fields: Record<string, any> | null | undefined) {
  return resolveMobileNodeTemplateProviderId(props.providers, fields)
}

async function loadTemplate(
  contextFields: Record<string, any> | null | undefined = props.config as Record<string, any> | null,
  preserveDraft = false,
) {
  const typeId = String(props.node?.type_id || '').trim()
  templateRequestId += 1
  const requestId = templateRequestId
  if (!props.open || !typeId) {
    templateSchema.value = {}
    fieldSchemaCache.value = {}
    templateFields.value = {}
    loadedSchemaContextKey = ''
    resetDraftFromConfig()
    return
  }
  loading.value = true
  try {
    const contextKey = schemaContextKey(contextFields)
    const template = await getNodeTemplate(typeId, { providerId: contextKey })
    if (requestId !== templateRequestId) return
    const nextSchema = (template.schema || {}) as Record<string, any>
    templateSchema.value = nextSchema
    fieldSchemaCache.value = preserveDraft
      ? { ...fieldSchemaCache.value, ...nextSchema }
      : { ...nextSchema }
    templateFields.value = { ...(template.fields || {}) }
    loadedSchemaContextKey = contextKey
    if (preserveDraft) {
      const config = props.config as Record<string, any> | null
      const nextDraft = { ...draftFields.value }
      for (const key of Object.keys(nextSchema)) {
        if (nextDraft[key] !== undefined) continue
        nextDraft[key] = config?.[key] ?? templateFields.value[key]
      }
      draftFields.value = nextDraft
    } else {
      resetDraftFromConfig()
    }
  } catch (e) {
    if (requestId !== templateRequestId) return
    templateSchema.value = {}
    fieldSchemaCache.value = {}
    templateFields.value = {}
    loadedSchemaContextKey = ''
    resetDraftFromConfig()
    showError(e)
  } finally {
    if (requestId === templateRequestId) loading.value = false
  }
}

async function persistPendingChanges(emitSaved = true) {
  if (loading.value) return false
  const nodeId = String(props.node?.id || '').trim()
  if (!nodeId) return false
  const keys = Object.keys(dirtyKeys.value || {})
  const shouldRename = nodeNameDirty.value
  const shouldSaveNote = noteDirty.value
  const nextNodeName = nodeNameDraft.value.trim()
  const nextNote = noteDraft.value.trim()
  if (!keys.length && !shouldRename && !shouldSaveNote) return true
  if (shouldRename && !nextNodeName) {
    showError('Node name is required')
    return false
  }

  const fields: Record<string, unknown> = {}
  for (const key of keys) {
    fields[key] = normalizeSchemaFieldValue(fieldSchemaCache.value, key, draftFields.value[key])
  }

  saving.value = true
  try {
    if (shouldRename) {
      await props.renameNode(nextNodeName)
      nodeNameTouched.value = false
      nodeNameDraft.value = nextNodeName
    }
    if (keys.length) {
      await props.saveFields(fields)
      dirtyKeys.value = {}
    }
    if (shouldSaveNote) {
      await props.saveNote(nextNote)
      noteDraft.value = nextNote
      noteTouched.value = false
    }
    if (emitSaved) emit('saved')
    return true
  } catch (e) {
    showError(e)
    return false
  } finally {
    saving.value = false
  }
}

function applyChanges() {
  void persistPendingChanges()
}

function defaultProfileId() {
  const normalize = (value: unknown) => String(value || '')
    .trim()
    .replace(/[^A-Za-z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return normalize(nodeNameDraft.value) || normalize(props.node?.id) || 'node_profile'
}

async function saveNodeProfile() {
  if (!props.node || profileSaving.value || saving.value) return
  const suggestedId = defaultProfileId()
  const profileId = String(window.prompt('Profile ID (existing ID will be overwritten)', suggestedId) || '').trim()
  if (!profileId) return
  if (!/^[A-Za-z0-9_-]+$/.test(profileId)) {
    showError('Profile ID may contain only letters, numbers, underscores, or hyphens')
    return
  }
  const suggestedName = nodeNameDraft.value.trim() || currentNodeName.value || profileId
  const profileName = String(window.prompt('Profile name', suggestedName) || '').trim() || profileId

  profileSaving.value = true
  profileSaved.value = false
  try {
    const persisted = await persistPendingChanges(false)
    if (!persisted) return
    await props.saveProfile(profileId, profileName)
    emit('saved')
    profileSaved.value = true
    if (profileSavedTimer != null) window.clearTimeout(profileSavedTimer)
    profileSavedTimer = window.setTimeout(() => {
      profileSaved.value = false
      profileSavedTimer = null
    }, 1800)
  } catch (e) {
    showError(e)
  } finally {
    profileSaving.value = false
  }
}

function openProfilePicker() {
  if (!props.node || saving.value || profileSaving.value) return
  profilePickerOpen.value = true
}

async function loadNodeProfile(profile: AgentProfile) {
  if (dirtyCount.value > 0 && !window.confirm('加载 Profile 将替换当前尚未保存的修改，是否继续？')) {
    return
  }
  saving.value = true
  try {
    const result = await props.loadProfile(profile.id)
    resetDraftFromConfig(result.config.after)
    profilePickerOpen.value = false
    resetNodeNameDraft()
    runtimeEventsRevision.value += 1
    emit('saved')
  } catch (e) {
    showError(e)
  } finally {
    saving.value = false
  }
}

watch(
  templateKey,
  () => {
    void loadTemplate()
  },
  { immediate: true },
)

watch(
  () => props.config,
  () => {
    if (saving.value || dirtyCount.value > 0) return
    resetDraftFromConfig()
  },
)

watch(
  () => schemaContextKey(draftFields.value),
  (contextKey) => {
    const typeId = String(props.node?.type_id || '').trim()
    if (typeId !== 'agent_node' && !HARNESS_NODE_TYPES.includes(typeId)) return
    // A provider change during an in-flight template request must supersede it.
    // Initial draft hydration is the only loading state that should be ignored.
    if (!props.open || (loading.value && !dirtyKeys.value.provider_id)) return
    if (!loading.value && contextKey === loadedSchemaContextKey) return
    void loadTemplate(draftFields.value, true)
  },
)

watch(
  () => [props.open, props.node?.id, props.node?.name],
  () => {
    if (saving.value || nodeNameTouched.value) return
    resetNodeNameDraft()
  },
  { immediate: true },
)

watch(
  () => [props.open, props.node?.id, props.node?.note],
  () => {
    if (saving.value || noteTouched.value) return
    resetNoteDraft()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (profileSavedTimer != null) window.clearTimeout(profileSavedTimer)
})
</script>

<template>
  <div v-if="open" class="config-backdrop" @click.self="emit('close')">
    <section class="config-sheet" role="dialog" aria-modal="true" :aria-label="t('mobile.openNodeConfig')">
      <header class="config-sheet-head">
        <div class="config-title-wrap">
          <div class="config-title-row">
            <FormTextInput
              class="config-title-input"
              :model-value="nodeNameDraft"
              :aria-label="t('board.nodeName')"
              :disabled="saving || profileSaving"
              @update:model-value="setNodeName"
            />
            <ActionButton
              compact
              :disabled="saving || profileSaving || !node"
              @click="openProfilePicker"
            >
              LoadProfile
            </ActionButton>
            <ActionButton
              variant="primary"
              compact
              :disabled="saving || profileSaving || !node"
              @click="saveNodeProfile"
            >
              {{ profileSaving ? 'Saving...' : (profileSaved ? 'Saved' : 'SaveProfile') }}
            </ActionButton>
          </div>
          <div class="config-subtitle">{{ node?.type_id || '' }}</div>
        </div>
        <DialogCloseButton :aria-label="t('common.close')" :disabled="profileSaving" @click="emit('close')" />
      </header>

      <div class="config-body">
        <section class="node-note-section">
          <div class="node-note-label">{{ t('board.note') }}</div>
          <ExpandableTextarea
            :model-value="noteDraft"
            :rows="3"
            :title="t('board.note')"
            :aria-label="t('board.note')"
            :placeholder="t('board.notePlaceholder')"
            :disabled="saving || profileSaving || !!node?.readonly"
            @update:model-value="setNote"
          />
          <div class="node-note-hint">{{ t('board.noteHint') }}</div>
        </section>

        <section class="config-fields-section">
          <div v-if="loading" class="config-empty">{{ t('board.loadingConfig') }}</div>
          <div v-else-if="fieldKeys.length === 0" class="config-empty">{{ t('board.noEditableFields') }}</div>
          <NodeConfigFields
            v-if="fieldKeys.length > 0"
            :type-id="node?.type_id || ''"
            :schema="schema"
            :fields="draftFields"
            :providers="providers"
            :available-tools="availableTools"
            enable-prompt-library
            @update-field="setField"
            @field-error="showError"
          />
        </section>

        <NodeRuntimeEventsFieldGroup
          :key="`${node?.id || ''}:${runtimeEventsRevision}`"
          v-if="node"
          :node="node"
          :graph-id="graphId"
          @error="showError"
        />

        <section class="output-routes-section">
          <div class="route-head">
            <div>
              <div class="route-title">{{ t('board.outputs') }}</div>
              <div class="route-subtitle">{{ t('board.outputHelp') }}</div>
            </div>
            <ActionButton class="route-add-btn" compact :disabled="!canAddRoute" @click="addRoute">
              {{ routing ? '保存中...' : '添加' }}
            </ActionButton>
          </div>

          <div v-if="targetNodes.length === 0" class="route-empty">{{ t('board.noRouteTargets') }}</div>
          <div v-else-if="outputRoutes.length === 0" class="route-empty">{{ t('board.noRoutes') }}</div>
          <div v-else class="route-list">
            <div v-for="route in outputRoutes" :key="route.id" class="route-row">
              <label>
                <span>{{ t('board.output') }}</span>
                <FormSelect :model-value="route.outputIndex" compact :disabled="routing" @change="setRouteOutput(route.id, $event)">
                  <option v-for="index in portOptions(node?.output_num || 1)" :key="index" :value="index">{{ index }}</option>
                </FormSelect>
              </label>
              <label>
                <span>{{ t('board.targetNode') }}</span>
                <FormSelect
                  :model-value="route.targetNodeId"
                  compact
                  :title="targetName(route.targetNodeId)"
                  :disabled="routing"
                  @change="setRouteTarget(route.id, $event)"
                >
                  <option v-for="target in targetNodes" :key="target.id" :value="target.id">
                    {{ target.name || target.id }}
                  </option>
                </FormSelect>
              </label>
              <label>
                <span>{{ t('board.input') }}</span>
                <FormSelect :model-value="route.inputIndex" compact :disabled="routing" @change="setRouteInput(route.id, $event)">
                  <option v-for="index in inputOptions(route.targetNodeId)" :key="index" :value="index">{{ index }}</option>
                </FormSelect>
              </label>
              <DangerButton icon :disabled="routing" :aria-label="t('board.removeRoute')" @click="removeRoute(route.id)">×</DangerButton>
            </div>
          </div>
        </section>

      </div>

      <footer class="config-actions">
        <ActionButton @click="emit('close')">{{ t('common.close') }}</ActionButton>
        <ActionButton variant="primary" :disabled="!canSave" @click="applyChanges">
          {{ saving ? '保存中...' : `保存${dirtyCount > 0 ? ` (${dirtyCount})` : ''}` }}
        </ActionButton>
      </footer>
    </section>
    <MobileNodeProfilePickerSheet
      :open="profilePickerOpen"
      :profiles="availableProfiles"
      @close="profilePickerOpen = false"
      @select="loadNodeProfile"
    />
  </div>
</template>

<style scoped>
.config-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: flex-end;
  background: var(--ui-dialog-backdrop);
}

.config-sheet {
  width: 100%;
  max-height: min(86vh, 760px);
  display: flex;
  flex-direction: column;
  border: 1px solid var(--ui-dialog-border);
  border-width: 1px 0 0;
  border-radius: var(--ui-dialog-radius) var(--ui-dialog-radius) 0 0;
  background: var(--ui-dialog-background);
  color: var(--ui-dialog-text);
  box-shadow: var(--ui-dialog-shadow);
}

.config-sheet-head,
.config-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
}

.config-sheet-head {
  justify-content: space-between;
  border-bottom: 1px solid var(--ui-dialog-divider);
}

.config-title-wrap {
  flex: 1;
  min-width: 0;
}

.config-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.config-title-input {
  flex: 1;
  width: auto;
  min-width: 0;
  font-size: 15px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.config-subtitle {
  margin-top: 2px;
  color: rgba(148, 163, 184, 0.88);
  font-size: 12px;
}

.config-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px;
}

.node-note-section,
.config-fields-section,
.output-routes-section {
  min-width: 0;
}

.node-note-section {
  display: grid;
  gap: 8px;
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.4);
}

.node-note-label {
  color: rgba(226, 232, 240, 0.96);
  font-size: 13px;
  font-weight: 700;
}

.node-note-hint {
  color: rgba(148, 163, 184, 0.88);
  font-size: 11px;
  line-height: 1.4;
}

.output-routes-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid rgba(148, 163, 184, 0.16);
}

.config-empty {
  padding: 12px;
  color: rgba(148, 163, 184, 0.95);
  font-size: 13px;
}

.route-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.route-title {
  color: rgba(248, 250, 252, 0.96);
  font-size: 14px;
  font-weight: 700;
}

.route-subtitle,
.route-empty {
  color: rgba(148, 163, 184, 0.92);
  font-size: 12px;
}

.route-empty {
  padding: 10px 0;
}

.route-add-btn {
  min-width: 64px;
}

.route-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.route-row {
  display: grid;
  grid-template-columns: minmax(58px, 0.65fr) minmax(0, 1.6fr) minmax(58px, 0.65fr) 34px;
  gap: 8px;
  align-items: end;
  padding: 8px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.38);
}

.route-row label {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.route-row span {
  color: rgba(148, 163, 184, 0.92);
  font-size: 11px;
}

.config-actions {
  justify-content: flex-end;
  border-top: 1px solid rgba(148, 163, 184, 0.16);
}

@media (max-width: 420px) {
  .route-row {
    grid-template-columns: 1fr 1fr 34px;
  }

  .route-row label:nth-child(2) {
    grid-column: 1 / -1;
    grid-row: 1;
  }
}
</style>
