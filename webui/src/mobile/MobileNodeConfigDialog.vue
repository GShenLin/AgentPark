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
import { resolveAgentProviderSchemaContext } from '../composables/useAgentNodeCreateSchema'
import NodeConfigFields from '../components/agent-board/NodeConfigFields.vue'
import MobileNodeProfilePickerSheet from './MobileNodeProfilePickerSheet.vue'
import NodeRuntimeEventsFieldGroup from '../components/agent-board/NodeRuntimeEventsFieldGroup.vue'
import type { MobileOutputRouteRow } from './useMobileWorkspace'

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
const routing = ref(false)
let templateRequestId = 0
let profileSavedTimer: number | null = null
let loadedSchemaContextKey = ''

const schema = computed(() => templateSchema.value)
const fieldKeys = computed(() => Object.keys(schema.value || {}))
const currentNodeName = computed(() => String(props.node?.name || props.node?.id || '').trim())
const nodeNameDirty = computed(() => nodeNameTouched.value && nodeNameDraft.value.trim() !== currentNodeName.value)
const dirtyCount = computed(() => Object.keys(dirtyKeys.value || {}).length + (nodeNameDirty.value ? 1 : 0))
const canSave = computed(() => dirtyCount.value > 0 && !saving.value && (!nodeNameDirty.value || !!nodeNameDraft.value.trim()))
const templateKey = computed(() => {
  if (!props.open) return 'closed'
  const nodeId = String(props.node?.id || '').trim()
  const typeId = String(props.node?.type_id || '').trim()
  return `${nodeId}:${typeId}`
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

function schemaContextKey(fields: Record<string, any> | null | undefined) {
  const context = resolveAgentProviderSchemaContext(props.providers, fields)
  return context.providerId
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
  const nodeId = String(props.node?.id || '').trim()
  if (!nodeId) return false
  const keys = Object.keys(dirtyKeys.value || {})
  const shouldRename = nodeNameDirty.value
  const nextNodeName = nodeNameDraft.value.trim()
  if (!keys.length && !shouldRename) return true
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
    if (String(props.node?.type_id || '').trim() !== 'agent_node') return
    if (loading.value || !props.open || contextKey === loadedSchemaContextKey) return
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

onBeforeUnmount(() => {
  if (profileSavedTimer != null) window.clearTimeout(profileSavedTimer)
})
</script>

<template>
  <div v-if="open" class="config-backdrop" @click.self="emit('close')">
    <section class="config-sheet" role="dialog" aria-modal="true" aria-label="节点配置">
      <header class="config-sheet-head">
        <div class="config-title-wrap">
          <div class="config-title-row">
            <input
              class="config-title-input"
              type="text"
              :value="nodeNameDraft"
              aria-label="节点名称"
              :disabled="saving || profileSaving"
              @input="setNodeName(($event.target as HTMLInputElement).value)"
            />
            <button
              class="load-profile-btn"
              type="button"
              :disabled="saving || profileSaving || !node"
              @click="openProfilePicker"
            >
              LoadProfile
            </button>
            <button
              class="save-profile-btn"
              type="button"
              :disabled="saving || profileSaving || !node"
              @click="saveNodeProfile"
            >
              {{ profileSaving ? 'Saving...' : (profileSaved ? 'Saved' : 'SaveProfile') }}
            </button>
          </div>
          <div class="config-subtitle">{{ node?.type_id || '' }}</div>
        </div>
        <button class="sheet-icon-btn" type="button" aria-label="关闭配置" :disabled="profileSaving" @click="emit('close')">x</button>
      </header>

      <div class="config-body">
        <section class="config-fields-section">
          <div v-if="loading" class="config-empty">Loading node config...</div>
          <div v-else-if="fieldKeys.length === 0" class="config-empty">This node has no editable fields.</div>
          <NodeConfigFields
            v-else
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
              <div class="route-title">输出</div>
              <div class="route-subtitle">配置此节点的输出目标</div>
            </div>
            <button class="secondary-btn route-add-btn" type="button" :disabled="!canAddRoute" @click="addRoute">
              {{ routing ? '保存中...' : '添加' }}
            </button>
          </div>

          <div v-if="targetNodes.length === 0" class="route-empty">Create another node before adding an output route.</div>
          <div v-else-if="outputRoutes.length === 0" class="route-empty">No output routes configured.</div>
          <div v-else class="route-list">
            <div v-for="route in outputRoutes" :key="route.id" class="route-row">
              <label>
                <span>输出口</span>
                <select :value="route.outputIndex" :disabled="routing" @change="setRouteOutput(route.id, ($event.target as HTMLSelectElement).value)">
                  <option v-for="index in portOptions(node?.output_num || 1)" :key="index" :value="index">{{ index }}</option>
                </select>
              </label>
              <label>
                <span>目标节点</span>
                <select
                  :value="route.targetNodeId"
                  :title="targetName(route.targetNodeId)"
                  :disabled="routing"
                  @change="setRouteTarget(route.id, ($event.target as HTMLSelectElement).value)"
                >
                  <option v-for="target in targetNodes" :key="target.id" :value="target.id">
                    {{ target.name || target.id }}
                  </option>
                </select>
              </label>
              <label>
                <span>输入口</span>
                <select :value="route.inputIndex" :disabled="routing" @change="setRouteInput(route.id, ($event.target as HTMLSelectElement).value)">
                  <option v-for="index in inputOptions(route.targetNodeId)" :key="index" :value="index">{{ index }}</option>
                </select>
              </label>
              <button class="route-remove-btn" type="button" :disabled="routing" aria-label="删除输出路由" @click="removeRoute(route.id)">x</button>
            </div>
          </div>
        </section>

      </div>

      <footer class="config-actions">
        <button class="secondary-btn" type="button" @click="emit('close')">关闭</button>
        <button class="primary-btn" type="button" :disabled="!canSave" @click="applyChanges">
          {{ saving ? '保存中...' : `保存${dirtyCount > 0 ? ` (${dirtyCount})` : ''}` }}
        </button>
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
  background: rgba(2, 6, 23, 0.72);
}

.config-sheet {
  width: 100%;
  max-height: min(86vh, 760px);
  display: flex;
  flex-direction: column;
  border-top: 1px solid rgba(148, 163, 184, 0.24);
  background: #08111f;
  box-shadow: 0 -18px 40px rgba(2, 6, 23, 0.42);
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
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
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
  height: 34px;
  padding: 0 9px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.72);
  color: rgba(248, 250, 252, 0.96);
  font-size: 15px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.load-profile-btn,
.save-profile-btn {
  flex: 0 0 auto;
  min-height: 34px;
  padding: 0 7px;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 700;
}

.load-profile-btn {
  border-color: rgba(56, 189, 248, 0.48);
  background: rgba(14, 116, 144, 0.28);
  color: rgba(224, 242, 254, 0.96);
}

.save-profile-btn {
  border-color: rgba(34, 197, 94, 0.48);
  background: rgba(22, 101, 52, 0.3);
  color: rgba(220, 252, 231, 0.96);
}

.load-profile-btn:disabled,
.save-profile-btn:disabled {
  opacity: 0.58;
}

.config-title-input:focus {
  border-color: rgba(56, 189, 248, 0.72);
  outline: none;
}

.config-subtitle {
  margin-top: 2px;
  color: rgba(148, 163, 184, 0.88);
  font-size: 12px;
}

.sheet-icon-btn {
  width: 34px;
  height: 34px;
  padding: 0;
  border-radius: 8px;
}

.config-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px;
}

.config-fields-section,
.output-routes-section {
  min-width: 0;
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

.route-row select {
  width: 100%;
  min-width: 0;
  height: 34px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.88);
  color: rgba(248, 250, 252, 0.96);
}

.route-remove-btn {
  width: 34px;
  height: 34px;
  padding: 0;
  border-color: rgba(248, 113, 113, 0.35);
  background: rgba(127, 29, 29, 0.24);
  color: #fecaca;
}

.config-actions {
  justify-content: flex-end;
  border-top: 1px solid rgba(148, 163, 184, 0.16);
}

.secondary-btn,
.primary-btn {
  min-width: 72px;
  min-height: 38px;
  border-radius: 8px;
}

.secondary-btn {
  border-color: rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.72);
}

.primary-btn {
  border-color: rgba(56, 189, 248, 0.48);
  background: rgba(14, 165, 233, 0.3);
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
