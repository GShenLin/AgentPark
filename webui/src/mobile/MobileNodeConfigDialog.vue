<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  getNodeTemplate,
  updateNodeInstanceConfig,
  type MobileNode,
  type NodeInstanceConfig,
  type ProviderInfo,
} from '../api'
import { normalizeSchemaFieldValue } from '../composables/nodeSchemaFields'
import NodeConfigFields from '../components/agent-board/NodeConfigFields.vue'

const props = defineProps<{
  open: boolean
  graphId: string
  node: MobileNode | null
  config: NodeInstanceConfig | null
  providers: ProviderInfo[]
  availableTools: string[]
}>()

const emit = defineEmits<{
  close: []
  saved: []
  error: [message: string]
}>()

const loading = ref(false)
const saving = ref(false)
const templateSchema = ref<Record<string, any>>({})
const templateFields = ref<Record<string, any>>({})
const draftFields = ref<Record<string, any>>({})
const dirtyKeys = ref<Record<string, true>>({})
let templateRequestId = 0

const schema = computed(() => templateSchema.value)
const fieldKeys = computed(() => Object.keys(schema.value || {}))
const dirtyCount = computed(() => Object.keys(dirtyKeys.value || {}).length)
const templateKey = computed(() => {
  if (!props.open) return 'closed'
  const nodeId = String(props.node?.id || '').trim()
  const typeId = String(props.node?.type_id || '').trim()
  return `${nodeId}:${typeId}`
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

function resetDraftFromConfig() {
  const cfg = props.config as Record<string, any> | null
  const next: Record<string, any> = {}
  for (const key of fieldKeys.value) {
    next[key] = cfg?.[key] ?? templateFields.value[key]
  }
  draftFields.value = next
  dirtyKeys.value = {}
}

async function loadTemplate() {
  const typeId = String(props.node?.type_id || '').trim()
  templateRequestId += 1
  const requestId = templateRequestId
  if (!props.open || !typeId) {
    templateSchema.value = {}
    templateFields.value = {}
    resetDraftFromConfig()
    return
  }
  loading.value = true
  try {
    const template = await getNodeTemplate(typeId)
    if (requestId !== templateRequestId) return
    templateSchema.value = (template.schema || {}) as Record<string, any>
    templateFields.value = { ...(template.fields || {}) }
    resetDraftFromConfig()
  } catch (e) {
    if (requestId !== templateRequestId) return
    templateSchema.value = {}
    templateFields.value = {}
    resetDraftFromConfig()
    showError(e)
  } finally {
    if (requestId === templateRequestId) loading.value = false
  }
}

async function applyChanges() {
  const nodeId = String(props.node?.id || '').trim()
  const graphId = String(props.graphId || '').trim() || 'default'
  if (!nodeId) return
  const keys = Object.keys(dirtyKeys.value || {})
  if (!keys.length) return

  const fields: Record<string, unknown> = {}
  for (const key of keys) {
    fields[key] = normalizeSchemaFieldValue(schema.value, key, draftFields.value[key])
  }

  saving.value = true
  try {
    await updateNodeInstanceConfig(nodeId, { fields }, graphId)
    dirtyKeys.value = {}
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
</script>

<template>
  <div v-if="open" class="config-backdrop" @click.self="emit('close')">
    <section class="config-sheet" role="dialog" aria-modal="true" aria-label="节点配置">
      <header class="config-sheet-head">
        <div class="config-title-wrap">
          <div class="config-title">{{ node?.name || node?.id || '节点配置' }}</div>
          <div class="config-subtitle">{{ node?.type_id || '' }}</div>
        </div>
        <button class="sheet-icon-btn" type="button" aria-label="关闭配置" @click="emit('close')">x</button>
      </header>

      <div class="config-body">
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
      </div>

      <footer class="config-actions">
        <button class="secondary-btn" type="button" @click="emit('close')">关闭</button>
        <button class="primary-btn" type="button" :disabled="dirtyCount === 0 || saving" @click="applyChanges">
          {{ saving ? '保存中...' : `保存${dirtyCount > 0 ? ` (${dirtyCount})` : ''}` }}
        </button>
      </footer>
    </section>
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
  min-width: 0;
}

.config-title {
  color: rgba(248, 250, 252, 0.96);
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

.config-empty {
  padding: 12px;
  color: rgba(148, 163, 184, 0.95);
  font-size: 13px;
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
</style>
