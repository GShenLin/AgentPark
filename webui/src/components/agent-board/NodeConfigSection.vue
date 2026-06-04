<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { getNodeTemplate, type NodeInstanceConfig, type ProviderInfo } from '../../api'
import { ASSET_FIELD_KEYS, mergeDroppedPaths, resolveDroppedPaths } from '../../composables/droppedPaths'
import { getSchemaFieldType, normalizeSchemaFieldValue } from '../../composables/nodeSchemaFields'
import { AgentBoardKey, type NodeCard } from './context'
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
let templateRequestId = 0

const schema = computed(() => templateSchema.value)
const fieldKeys = computed(() => Object.keys(schema.value || {}))
const dirtyCount = computed(() => Object.keys(dirtyKeys.value || {}).length)

function showError(message: string) {
  emit('error', String(message || '').trim())
}

function getFieldType(key: string) {
  return getSchemaFieldType(schema.value, key)
}

function setField(key: string, value: any) {
  draftFields.value = { ...draftFields.value, [key]: value }
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
    loading.value = false
    return
  }
  loading.value = true
  try {
    await ctx.ensureNodeConfig(targetId).catch(() => null)
    await loadTemplate(String(props.node?.typeId || '').trim())
    resetDraftFromConfig()
  } finally {
    loading.value = false
  }
}

async function applyChanges() {
  const nodeId = props.node?.id
  if (!nodeId) return
  const keys = Object.keys(dirtyKeys.value || {})
  if (!keys.length) return

  const fields: Record<string, unknown> = {}
  for (const key of keys) {
    fields[key] = normalizeSchemaFieldValue(schema.value, key, draftFields.value[key])
  }

  applying.value = true
  showError('')
  try {
    await ctx.setNodeFields(nodeId, fields)
    await ctx.ensureNodeConfig(nodeId).catch(() => null)
    dirtyKeys.value = {}
  } catch (e: any) {
    showError(String(e?.message || e))
  } finally {
    applying.value = false
  }
}

function hasDroppedPayload(event: DragEvent) {
  const internal = String(event.dataTransfer?.getData('application/x-aitools-file') || '').trim()
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
      enable-asset-drop
      @update-field="setField"
      @field-dragover="onFieldDragOver"
      @field-dragleave="onFieldDragLeave"
      @field-drop="onFieldDrop"
      @field-error="showError"
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
  flex: 0 1 auto;
  min-height: 0;
  justify-content: flex-start;
  overflow: hidden;
  border-top: 1px solid rgba(148, 163, 184, 0.28);
  padding-top: 16px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
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

.field-list {
  flex: 0 1 auto;
  min-height: 0;
  max-height: 260px;
  gap: 12px;
  overflow: auto;
  padding-right: 4px;
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
</style>
