<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getNodeTemplate, type AgentProfile, type NodeInfo, type ProviderInfo } from '../api'
import ActionButton from '../components/ActionButton.vue'
import NodeConfigFields from '../components/agent-board/NodeConfigFields.vue'
import DialogCloseButton from '../components/DialogCloseButton.vue'
import FormSelect from '../components/FormSelect.vue'
import FormTextInput from '../components/FormTextInput.vue'
import { normalizeSchemaFieldValue } from '../composables/nodeSchemaFields'
import { useAgentNodeCreateSchema } from '../composables/useAgentNodeCreateSchema'
import { useProviderDrivenTemplateSchema } from '../composables/useProviderDrivenTemplateSchema'
import { t } from '../i18n'

const props = defineProps<{
  open: boolean
  nodeTypes: NodeInfo[]
  agentProfiles: AgentProfile[]
  providers: ProviderInfo[]
  availableTools: string[]
}>()

const emit = defineEmits<{
  close: []
  create: [payload: { typeId: string; nodeName: string; fields: Record<string, unknown> }]
  createProfile: [profileId: string]
  error: [message: string]
}>()

const loading = ref(false)
const creating = ref(false)
const creatingProfile = ref(false)
const selectedProfileId = ref('')
const selectedTypeId = ref('')
const selectedNodeName = ref('')
const selectedNodeSchema = ref<Record<string, any>>({})
const selectedNodeFields = ref<Record<string, any>>({})
let requestId = 0

const providersRef = computed(() => props.providers)
const toolsRef = computed(() => props.availableTools)
const fieldKeys = computed(() => Object.keys(selectedNodeSchema.value || {}))

const {
  toolOptions,
  createProviderOptions,
  ensureCreateAgentSelections,
} = useAgentNodeCreateSchema({
  selectedTypeId,
  selectedNodeFields,
  providers: providersRef,
  availableTools: toolsRef,
})
const { loading: providerSchemaLoading } = useProviderDrivenTemplateSchema({
  typeId: selectedTypeId,
  fields: selectedNodeFields,
  schema: selectedNodeSchema,
  onError: showError,
})

function showError(value: unknown) {
  emit('error', String((value as { message?: unknown })?.message || value || '').trim())
}

function setSelectedNodeField(key: string, value: any) {
  selectedNodeFields.value = { ...selectedNodeFields.value, [key]: value }
}

function resetSelection() {
  selectedProfileId.value = ''
  selectedTypeId.value = ''
  selectedNodeName.value = ''
  selectedNodeSchema.value = {}
  selectedNodeFields.value = {}
}

async function createFromProfile() {
  const profileId = String(selectedProfileId.value || '').trim()
  if (!profileId) return
  creatingProfile.value = true
  try {
    emit('createProfile', profileId)
  } finally {
    creatingProfile.value = false
  }
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
  for (const key of Object.keys(selectedNodeSchema.value || {})) {
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
    createProviderOptions.value.join('|'),
    toolOptions.value.join('|'),
  ],
  () => {
    ensureCreateAgentSelections()
  },
)
</script>

<template>
  <div v-if="open" class="create-backdrop" @click.self="emit('close')">
    <section class="create-sheet" role="dialog" aria-modal="true" :aria-label="t('board.createNode')">
      <header class="create-head">
        <div>
          <div class="create-title">{{ t('board.createNode') }}</div>
          <div class="create-subtitle">{{ selectedTypeId || 'Choose a node type' }}</div>
        </div>
        <DialogCloseButton :aria-label="t('common.close')" @click="emit('close')" />
      </header>

      <div class="create-body">
        <section v-if="agentProfiles.length" class="preset-panel">
          <div class="preset-title">{{ t('board.nodePreset') }}</div>
          <div class="preset-row">
            <FormSelect v-model="selectedProfileId" :disabled="creatingProfile || creating">
              <option value="">{{ t('board.choosePreset') }}</option>
              <option v-for="profile in agentProfiles" :key="profile.id" :value="profile.id">
                {{ profile.name || profile.id }}
              </option>
            </FormSelect>
            <ActionButton class="preset-btn" variant="primary" :disabled="!selectedProfileId || creatingProfile" @click="createFromProfile">
              {{ creatingProfile ? 'Creating...' : 'Create' }}
            </ActionButton>
          </div>
        </section>

        <div class="node-type-list">
          <button
            v-for="node in nodeTypes"
            :key="node.id"
            class="node-type-btn"
            type="button"
            :class="{ selected: selectedTypeId === node.id }"
            :disabled="loading || creating || creatingProfile"
            @click="selectNodeType(node)"
          >
            <span class="node-type-name">{{ node.name || node.id }}</span>
            <span v-if="node.description" class="node-type-desc">{{ node.description }}</span>
          </button>
        </div>

        <div v-if="loading" class="create-empty">{{ t('board.loadingSettings') }}</div>
        <template v-else-if="selectedTypeId">
          <label class="field">
            <span class="field-label">{{ t('board.nodeName') }}</span>
            <FormTextInput v-model="selectedNodeName" />
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
        <ActionButton @click="emit('close')">{{ t('common.cancel') }}</ActionButton>
        <ActionButton variant="primary" :disabled="!selectedTypeId || creating || providerSchemaLoading" @click="createNode">
          {{ creating ? 'Creating...' : 'Create' }}
        </ActionButton>
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
  background: var(--ui-dialog-backdrop);
}

.create-sheet {
  width: 100%;
  max-height: min(88vh, 780px);
  display: flex;
  flex-direction: column;
  border: 1px solid var(--ui-dialog-border);
  border-width: 1px 0 0;
  border-radius: var(--ui-dialog-radius) var(--ui-dialog-radius) 0 0;
  background: var(--ui-dialog-background);
  color: var(--ui-dialog-text);
  box-shadow: var(--ui-dialog-shadow);
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
  border-bottom: 1px solid var(--ui-dialog-divider);
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

.preset-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.58);
}

.preset-title {
  color: rgba(203, 213, 225, 0.92);
  font-size: 12px;
  font-weight: 700;
}

.preset-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.preset-btn {
  min-width: 84px;
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

.create-empty {
  padding: 10px;
  color: rgba(148, 163, 184, 0.95);
  font-size: 13px;
}

.create-actions {
  justify-content: flex-end;
  border-top: 1px solid rgba(148, 163, 184, 0.16);
}

</style>
