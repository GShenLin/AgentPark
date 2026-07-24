<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  getNodeTemplate,
  listAgentProfiles,
  updateAgentProfile,
  type AgentProfile,
  type AgentProfileEditorPayload,
  type ProviderInfo,
} from '../../api'
import { normalizeSchemaFieldValue } from '../../composables/nodeSchemaFields'
import { resolveAgentProviderSchemaContext } from '../../composables/useAgentNodeCreateSchema'
import NodeConfigFields from '../agent-board/NodeConfigFields.vue'

const props = defineProps<{
  providers: ProviderInfo[]
  availableTools: string[]
}>()

const emit = defineEmits<{
  error: [message: string]
  status: [message: string]
  dirty: [value: boolean]
}>()

const profiles = ref<AgentProfile[]>([])
const selectedProfileId = ref('')
const profileName = ref('')
const nodeTypeId = ref('')
const sourceGraphId = ref('')
const sourceNodeId = ref('')
const nodeName = ref('')
const templateSchema = ref<Record<string, any>>({})
const fieldSchemaCache = ref<Record<string, any>>({})
const draftFields = ref<Record<string, any>>({})
const persistedFieldKeys = ref<string[]>([])
const editedFieldKeys = ref<Record<string, true>>({})
const eventRulesContent = ref('{}\n')
const baseline = ref('')
const loading = ref(false)
const templateLoading = ref(false)
const saving = ref(false)
const localError = ref('')
let templateRequestId = 0
let loadedSchemaContextKey = ''

const selectedProfile = computed(() => {
  return profiles.value.find((profile) => profile.id === selectedProfileId.value) || null
})

const schemaFieldCount = computed(() => Object.keys(templateSchema.value).length)
const serializedDraft = computed(() => JSON.stringify({
  profileName: profileName.value,
  nodeTypeId: nodeTypeId.value,
  sourceGraphId: sourceGraphId.value,
  sourceNodeId: sourceNodeId.value,
  nodeName: nodeName.value,
  fields: draftFields.value,
  eventRulesContent: eventRulesContent.value,
}))
const dirty = computed(() => Boolean(selectedProfile.value) && serializedDraft.value !== baseline.value)

watch(dirty, (value) => emit('dirty', value), { immediate: true })

function showError(error: unknown) {
  const message = String((error as { message?: unknown })?.message || error || '').trim()
  localError.value = message
  emit('error', message)
}

function profileFieldDraft(profile: AgentProfile, templateFields: Record<string, any>) {
  return {
    ...templateFields,
    ...(profile.fields || {}),
  }
}

function schemaContextKey(fields: Record<string, any> | null | undefined) {
  const context = resolveAgentProviderSchemaContext(props.providers, fields)
  return context.providerId
}

async function refreshTemplateSchema(contextFields: Record<string, any>) {
  if (nodeTypeId.value !== 'agent_node') return
  const contextKey = schemaContextKey(contextFields)
  if (contextKey === loadedSchemaContextKey) return
  templateRequestId += 1
  const requestId = templateRequestId
  try {
    const template = await getNodeTemplate(nodeTypeId.value, { providerId: contextKey })
    if (requestId !== templateRequestId) return
    const nextSchema = (template.schema || {}) as Record<string, any>
    templateSchema.value = nextSchema
    fieldSchemaCache.value = { ...fieldSchemaCache.value, ...nextSchema }
    const nextDraft = { ...draftFields.value }
    for (const key of Object.keys(nextSchema)) {
      if (nextDraft[key] !== undefined) continue
      nextDraft[key] = template.fields?.[key]
    }
    draftFields.value = nextDraft
    loadedSchemaContextKey = contextKey
  } catch (error) {
    if (requestId === templateRequestId) showError(error)
  }
}

async function loadProfileDraft(profile: AgentProfile | null) {
  localError.value = ''
  templateRequestId += 1
  const requestId = templateRequestId

  if (!profile) {
    profileName.value = ''
    nodeTypeId.value = ''
    sourceGraphId.value = ''
    sourceNodeId.value = ''
    nodeName.value = ''
    templateSchema.value = {}
    fieldSchemaCache.value = {}
    draftFields.value = {}
    loadedSchemaContextKey = ''
    persistedFieldKeys.value = []
    editedFieldKeys.value = {}
    eventRulesContent.value = '{}\n'
    baseline.value = serializedDraft.value
    return
  }

  profileName.value = String(profile.name || profile.id)
  nodeTypeId.value = String(profile.node_type_id || '')
  sourceGraphId.value = String(profile.source_graph_id || '')
  sourceNodeId.value = String(profile.source_node_id || '')
  nodeName.value = String(profile.node_name || '')
  persistedFieldKeys.value = Object.keys(profile.fields || {})
  editedFieldKeys.value = {}
  eventRulesContent.value = `${JSON.stringify(profile.event_rules || {}, null, 2)}\n`
  templateSchema.value = {}
  draftFields.value = { ...(profile.fields || {}) }

  templateLoading.value = true
  try {
    const contextKey = schemaContextKey(profile.fields || {})
    const template = await getNodeTemplate(nodeTypeId.value, { providerId: contextKey })
    if (requestId !== templateRequestId) return
    templateSchema.value = (template.schema || {}) as Record<string, any>
    fieldSchemaCache.value = { ...templateSchema.value }
    draftFields.value = profileFieldDraft(profile, { ...(template.fields || {}) })
    loadedSchemaContextKey = contextKey
  } catch (error) {
    if (requestId !== templateRequestId) return
    templateSchema.value = {}
    fieldSchemaCache.value = {}
    draftFields.value = { ...(profile.fields || {}) }
    loadedSchemaContextKey = ''
    showError(error)
  } finally {
    if (requestId === templateRequestId) {
      templateLoading.value = false
      baseline.value = serializedDraft.value
    }
  }
}

async function loadProfiles(preferredId = selectedProfileId.value) {
  loading.value = true
  localError.value = ''
  try {
    const nextProfiles = await listAgentProfiles()
    profiles.value = nextProfiles
    const nextId = nextProfiles.some((profile) => profile.id === preferredId)
      ? preferredId
      : (nextProfiles[0]?.id || '')
    selectedProfileId.value = nextId
    await loadProfileDraft(nextProfiles.find((profile) => profile.id === nextId) || null)
  } catch (error) {
    showError(error)
  } finally {
    loading.value = false
  }
}

async function selectProfile(profileId: string) {
  if (profileId === selectedProfileId.value) return
  if (!confirmDiscard()) return
  selectedProfileId.value = profileId
  await loadProfileDraft(profiles.value.find((profile) => profile.id === profileId) || null)
}

function confirmDiscard() {
  return !dirty.value || window.confirm('Discard unsaved NodeProfiler changes?')
}

async function reloadProfiles() {
  if (!confirmDiscard()) return
  await loadProfiles()
}

function setNodeField(key: string, value: any) {
  draftFields.value = {
    ...draftFields.value,
    [key]: value,
  }
  editedFieldKeys.value = {
    ...editedFieldKeys.value,
    [key]: true,
  }
  localError.value = ''
}

function parseEventRules() {
  const eventRules = JSON.parse(eventRulesContent.value || '{}')
  if (!eventRules || typeof eventRules !== 'object' || Array.isArray(eventRules)) {
    throw new Error('Event rules must be a JSON object.')
  }
  return eventRules as Record<string, Array<Record<string, unknown>>>
}

function formatEventRules() {
  localError.value = ''
  try {
    eventRulesContent.value = `${JSON.stringify(parseEventRules(), null, 2)}\n`
  } catch (error) {
    showError(error)
  }
}

function optionalText(value: string) {
  const text = String(value || '').trim()
  return text || undefined
}

function parsePayload(): AgentProfileEditorPayload {
  const name = profileName.value.trim()
  const typeId = nodeTypeId.value.trim()
  if (!name) throw new Error('Profile name is required.')
  if (!typeId) throw new Error('Node type is required.')

  const includedKeys = new Set([
    ...persistedFieldKeys.value,
    ...Object.keys(editedFieldKeys.value),
  ])
  const fields: Record<string, unknown> = {}
  for (const key of includedKeys) {
    fields[key] = normalizeSchemaFieldValue(fieldSchemaCache.value, key, draftFields.value[key])
  }

  const instructionValue = fields.instruction
  const systemPromptValue = fields.system_prompt
  if (instructionValue != null && typeof instructionValue !== 'string') {
    throw new Error('Instruction must be text.')
  }
  if (systemPromptValue != null && typeof systemPromptValue !== 'string') {
    throw new Error('System prompt must be text.')
  }
  delete fields.instruction
  delete fields.system_prompt

  return {
    node_profiler: {
      name,
      node_type_id: typeId,
      ...(optionalText(sourceGraphId.value) ? { source_graph_id: optionalText(sourceGraphId.value) } : {}),
      ...(optionalText(sourceNodeId.value) ? { source_node_id: optionalText(sourceNodeId.value) } : {}),
      ...(optionalText(nodeName.value) ? { node_name: optionalText(nodeName.value) } : {}),
      fields,
      event_rules: parseEventRules(),
    },
    instruction: instructionValue || '',
    system_prompt: systemPromptValue || '',
  }
}

async function saveProfile() {
  const profileId = selectedProfileId.value
  if (!profileId || saving.value) return
  saving.value = true
  localError.value = ''
  try {
    const result = await updateAgentProfile(profileId, parsePayload())
    const index = profiles.value.findIndex((profile) => profile.id === profileId)
    if (index >= 0) profiles.value.splice(index, 1, result.profile)
    profiles.value.sort((left, right) => String(left.name || left.id).localeCompare(String(right.name || right.id)))
    await loadProfileDraft(result.profile)
    emit('status', `Saved ${profileId}`)
  } catch (error) {
    showError(error)
  } finally {
    saving.value = false
  }
}

watch(
  () => schemaContextKey(draftFields.value),
  (contextKey) => {
    if (nodeTypeId.value !== 'agent_node' || templateLoading.value) return
    if (contextKey === loadedSchemaContextKey) return
    void refreshTemplateSchema(draftFields.value)
  },
)

onMounted(() => loadProfiles())
</script>

<template>
  <div class="profiler-editor">
    <aside class="profiler-browser" aria-label="Node profilers">
      <div class="profiler-browser-head">
        <strong>Profiles</strong>
        <span>{{ profiles.length }}</span>
      </div>
      <button
        v-for="profile in profiles"
        :key="profile.id"
        type="button"
        class="profiler-option"
        :class="{ active: profile.id === selectedProfileId }"
        :disabled="loading || templateLoading || saving"
        @click="selectProfile(profile.id)"
      >
        <span>{{ profile.name || profile.id }}</span>
        <small>{{ profile.id }}</small>
      </button>
      <div v-if="!loading && profiles.length === 0" class="profiler-empty">
        No Agent Profiles found in agent/*.json.
      </div>
    </aside>

    <section class="profiler-workspace">
      <div class="profiler-toolbar">
        <div class="profiler-heading">
          <strong>{{ selectedProfile?.name || 'NodeProfilerEditor' }}</strong>
          <span v-if="selectedProfile">{{ selectedProfile.id }} · {{ selectedProfile.node_type_id }}</span>
          <em v-if="dirty">Unsaved</em>
        </div>
        <div class="profiler-actions">
          <button type="button" :disabled="loading || templateLoading || saving" @click="reloadProfiles">Reload</button>
          <button class="primary" type="button" :disabled="!dirty || loading || templateLoading || saving" @click="saveProfile">
            {{ saving ? 'Saving...' : 'Save Profile' }}
          </button>
        </div>
      </div>

      <div v-if="selectedProfile" class="profiler-panels">
        <section class="profiler-panel node-profiler-panel">
          <div class="profiler-panel-head">
            <div>
              <h2>Node configuration</h2>
              <p>Uses the same schema-driven configuration panel as nodes on the board.</p>
            </div>
            <span v-if="schemaFieldCount" class="profiler-field-count">{{ schemaFieldCount }} fields</span>
          </div>

          <div class="profiler-config-body">
            <label class="profiler-name-field">
              <span>Profile name</span>
              <input v-model="profileName" type="text" :disabled="saving" />
            </label>

            <div v-if="templateLoading" class="profiler-placeholder compact">Loading node configuration...</div>
            <div v-else-if="schemaFieldCount === 0" class="profiler-placeholder compact">
              No editable schema is available for {{ nodeTypeId }}.
            </div>
            <NodeConfigFields
              v-else
              :type-id="nodeTypeId"
              :schema="templateSchema"
              :fields="draftFields"
              :providers="props.providers"
              :available-tools="props.availableTools"
              enable-prompt-library
              :reset-key="selectedProfileId"
              @update-field="setNodeField"
              @field-error="showError"
            />

            <details class="profiler-advanced">
              <summary>
                <span>Profile metadata and event rules</span>
                <span aria-hidden="true">›</span>
              </summary>
              <div class="profiler-advanced-content">
                <div class="profiler-metadata-grid">
                  <label>
                    <span>Node type</span>
                    <input :value="nodeTypeId" type="text" readonly />
                  </label>
                  <label>
                    <span>Node name</span>
                    <input v-model="nodeName" type="text" placeholder="Optional" />
                  </label>
                  <label>
                    <span>Source graph</span>
                    <input v-model="sourceGraphId" type="text" placeholder="Optional" />
                  </label>
                  <label>
                    <span>Source node</span>
                    <input v-model="sourceNodeId" type="text" placeholder="Optional" />
                  </label>
                </div>
                <div class="profiler-event-head">
                  <div>
                    <strong>Event rules</strong>
                    <span>Advanced profile data; preserved independently from node fields.</span>
                  </div>
                  <button type="button" :disabled="saving" @click="formatEventRules">Format</button>
                </div>
                <textarea
                  v-model="eventRulesContent"
                  spellcheck="false"
                  aria-label="Profile event rules JSON"
                ></textarea>
              </div>
            </details>
          </div>
        </section>
      </div>

      <div v-else-if="loading" class="profiler-placeholder">Loading profiles...</div>
      <div v-else class="profiler-placeholder">Select an existing profile to preview and edit it.</div>
      <div v-if="localError" class="profiler-error">{{ localError }}</div>
    </section>
  </div>
</template>

<style scoped src="./NodeProfilerEditor.css"></style>
