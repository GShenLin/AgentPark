<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getNodeTemplate, type NodeInfo, type ProviderInfo } from '../api'
import NodeConfigFields from '../components/agent-board/NodeConfigFields.vue'
import { normalizeSchemaFieldValue } from '../composables/nodeSchemaFields'
import { useAgentNodeCreateSchema } from '../composables/useAgentNodeCreateSchema'

const props = defineProps<{
  open: boolean
  nodeTypes: NodeInfo[]
  providers: ProviderInfo[]
  availableTools: string[]
}>()

const emit = defineEmits<{
  close: []
  create: [payload: { typeId: string; nodeName: string; fields: Record<string, unknown> }]
  error: [message: string]
}>()

const loading = ref(false)
const creating = ref(false)
const selectedTypeId = ref('')
const selectedNodeName = ref('')
const selectedNodeSchema = ref<Record<string, any>>({})
const selectedNodeFields = ref<Record<string, any>>({})
let requestId = 0

const providersRef = computed(() => props.providers)
const toolsRef = computed(() => props.availableTools)
const fieldKeys = computed(() => Object.keys(selectedNodeSchema.value || {}))

const {
  modeOptions,
  toolOptions,
  createProviderOptions,
  ensureCreateAgentSelections,
} = useAgentNodeCreateSchema({
  selectedTypeId,
  selectedNodeFields,
  providers: providersRef,
  availableTools: toolsRef,
})

function showError(value: unknown) {
  emit('error', String((value as { message?: unknown })?.message || value || '').trim())
}

function setSelectedNodeField(key: string, value: any) {
  selectedNodeFields.value = { ...selectedNodeFields.value, [key]: value }
}

function resetSelection() {
  selectedTypeId.value = ''
  selectedNodeName.value = ''
  selectedNodeSchema.value = {}
  selectedNodeFields.value = {}
}

async function selectNodeType(node: NodeInfo) {
  const typeId = String(node.id || '').trim()
  if (!typeId) return
  loading.value = true
  requestId += 1
  const currentRequest = requestId
  try {
    const template = await getNodeTemplate(typeId)
    if (currentRequest !== requestId) return
    selectedTypeId.value = typeId
    selectedNodeName.value = String(template.name || node.name || typeId)
    selectedNodeSchema.value = (template.schema || {}) as Record<string, any>
    selectedNodeFields.value = { ...(template.fields || {}) }
    ensureCreateAgentSelections()
  } catch (e) {
    if (currentRequest === requestId) showError(e)
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}

async function createNode() {
  const typeId = String(selectedTypeId.value || '').trim()
  if (!typeId) return
  const fields: Record<string, unknown> = {}
  for (const key of Object.keys(selectedNodeFields.value || {})) {
    fields[key] = normalizeSchemaFieldValue(selectedNodeSchema.value, key, selectedNodeFields.value[key])
  }
  creating.value = true
  try {
    emit('create', {
      typeId,
      nodeName: selectedNodeName.value,
      fields,
    })
  } finally {
    creating.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open) resetSelection()
  },
)

watch(
  () => [
    selectedTypeId.value,
    modeOptions.value.join('|'),
    createProviderOptions.value.join('|'),
    toolOptions.value.join('|'),
    String(selectedNodeFields.value.mode ?? ''),
  ],
  () => {
    ensureCreateAgentSelections()
  },
)
</script>

<template>
  <div v-if="open" class="create-backdrop" @click.self="emit('close')">
    <section class="create-sheet" role="dialog" aria-modal="true" aria-label="Create node">
      <header class="create-head">
        <div>
          <div class="create-title">Create Node</div>
          <div class="create-subtitle">{{ selectedTypeId || 'Choose a node type' }}</div>
        </div>
        <button class="sheet-icon-btn" type="button" aria-label="Close" @click="emit('close')">x</button>
      </header>

      <div class="create-body">
        <div class="node-type-list">
          <button
            v-for="node in nodeTypes"
            :key="node.id"
            class="node-type-btn"
            type="button"
            :class="{ selected: selectedTypeId === node.id }"
            :disabled="loading || creating"
            @click="selectNodeType(node)"
          >
            <span class="node-type-name">{{ node.name || node.id }}</span>
            <span v-if="node.description" class="node-type-desc">{{ node.description }}</span>
          </button>
        </div>

        <div v-if="loading" class="create-empty">Loading node settings...</div>
        <template v-else-if="selectedTypeId">
          <label class="field">
            <span class="field-label">Node name</span>
            <input v-model="selectedNodeName" class="field-input" type="text" />
          </label>

          <NodeConfigFields
            v-if="fieldKeys.length"
            :type-id="selectedTypeId"
            :schema="selectedNodeSchema"
            :fields="selectedNodeFields"
            :providers="providers"
            :available-tools="availableTools"
            @update-field="setSelectedNodeField"
            @field-error="showError"
          />
        </template>
      </div>

      <footer class="create-actions">
        <button class="secondary-btn" type="button" @click="emit('close')">Cancel</button>
        <button class="primary-btn" type="button" :disabled="!selectedTypeId || creating" @click="createNode">
          {{ creating ? 'Creating...' : 'Create' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.create-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: flex-end;
  background: rgba(2, 6, 23, 0.72);
}

.create-sheet {
  width: 100%;
  max-height: min(88vh, 780px);
  display: flex;
  flex-direction: column;
  border-top: 1px solid rgba(148, 163, 184, 0.24);
  background: #08111f;
  box-shadow: 0 -18px 40px rgba(2, 6, 23, 0.42);
}

.create-head,
.create-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
}

.create-head {
  justify-content: space-between;
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
}

.create-title {
  color: rgba(248, 250, 252, 0.96);
  font-size: 15px;
  font-weight: 700;
}

.create-subtitle,
.node-type-desc {
  color: rgba(148, 163, 184, 0.88);
  font-size: 12px;
}

.sheet-icon-btn {
  width: 34px;
  height: 34px;
  padding: 0;
  border-radius: 8px;
}

.create-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
}

.node-type-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(138px, 1fr));
  gap: 8px;
}

.node-type-btn {
  min-height: 56px;
  padding: 9px 10px;
  border-radius: 8px;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 3px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(15, 23, 42, 0.72);
}

.node-type-btn.selected {
  border-color: rgba(56, 189, 248, 0.62);
  background: rgba(14, 165, 233, 0.2);
}

.node-type-name {
  color: rgba(248, 250, 252, 0.96);
  font-size: 13px;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.node-type-desc {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.35;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  color: rgba(203, 213, 225, 0.92);
  font-size: 12px;
}

.field-input {
  min-height: 38px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  color: rgba(248, 250, 252, 0.96);
  background: rgba(15, 23, 42, 0.78);
}

.create-empty {
  padding: 10px;
  color: rgba(148, 163, 184, 0.95);
  font-size: 13px;
}

.create-actions {
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
