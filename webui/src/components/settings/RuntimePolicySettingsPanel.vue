<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  getRuntimePolicySettings,
  updateDefaultRuntimePolicy,
  updateRuntimePolicy,
  type RuntimePolicySettingsDocument,
  type RuntimePolicySettingsEntry,
} from '../../settingsApi'
import ActionButton from '../ActionButton.vue'
import FormSelect from '../FormSelect.vue'
import RuntimePolicyConfigForm from './RuntimePolicyConfigForm.vue'

const emit = defineEmits<{
  dirty: [value: boolean]
  error: [message: string]
  status: [message: string]
}>()

const document = ref<RuntimePolicySettingsDocument | null>(null)
const selectedPolicyId = ref('')
const defaultPolicyId = ref('')
const policyDraft = ref<Record<string, unknown> | null>(null)
const policyBaseline = ref('')
const loading = ref(false)
const savingDefault = ref(false)
const savingPolicy = ref(false)

const selectedPolicy = computed<RuntimePolicySettingsEntry | null>(() => (
  document.value?.policies.find((item) => item.policy_id === selectedPolicyId.value) || null
))
const defaultDirty = computed(() => (
  Boolean(document.value) && defaultPolicyId.value !== document.value?.default_policy_id
))
const policyDirty = computed(() => (
  JSON.stringify(policyDraft.value) !== policyBaseline.value
))
const dirty = computed(() => defaultDirty.value || policyDirty.value)

watch(dirty, (value) => emit('dirty', value), { immediate: true })

function reportError(error: unknown) {
  emit('error', String((error as { message?: unknown })?.message || error || '').trim())
}

function clonePolicyConfig(policy: RuntimePolicySettingsEntry | null) {
  return policy
    ? JSON.parse(JSON.stringify(policy.config)) as Record<string, unknown>
    : null
}

function loadSelectedPolicyDraft(policyId = selectedPolicyId.value) {
  const policy = document.value?.policies.find((item) => item.policy_id === policyId) || null
  selectedPolicyId.value = policy?.policy_id || document.value?.policies[0]?.policy_id || ''
  const resolved = document.value?.policies.find((item) => item.policy_id === selectedPolicyId.value) || null
  policyDraft.value = clonePolicyConfig(resolved)
  policyBaseline.value = JSON.stringify(policyDraft.value)
}

function applyDocument(next: RuntimePolicySettingsDocument, preferredPolicyId = selectedPolicyId.value) {
  document.value = next
  defaultPolicyId.value = next.default_policy_id
  loadSelectedPolicyDraft(preferredPolicyId)
}

async function reload() {
  if (dirty.value && !window.confirm('Discard unsaved RuntimePolicy changes?')) return
  loading.value = true
  emit('error', '')
  emit('status', '')
  try {
    applyDocument(await getRuntimePolicySettings())
  } catch (error) {
    reportError(error)
  } finally {
    loading.value = false
  }
}

function selectPolicy(policyId: string) {
  if (policyId === selectedPolicyId.value) return
  if (policyDirty.value && !window.confirm('Discard unsaved policy configuration?')) return
  loadSelectedPolicyDraft(policyId)
  emit('error', '')
  emit('status', '')
}

async function saveDefault() {
  if (!defaultDirty.value || savingDefault.value) return
  savingDefault.value = true
  emit('error', '')
  emit('status', '')
  try {
    const next = await updateDefaultRuntimePolicy(defaultPolicyId.value)
    const preferredPolicyId = selectedPolicyId.value
    const draft = policyDraft.value
    const baseline = policyBaseline.value
    document.value = next
    defaultPolicyId.value = next.default_policy_id
    selectedPolicyId.value = preferredPolicyId
    policyDraft.value = draft
    policyBaseline.value = baseline
    emit('status', `Default RuntimePolicy set to ${next.default_policy_id}`)
  } catch (error) {
    reportError(error)
  } finally {
    savingDefault.value = false
  }
}

async function savePolicy() {
  const policyId = selectedPolicyId.value
  if (!policyId || !policyDraft.value || !policyDirty.value || savingPolicy.value) return
  savingPolicy.value = true
  emit('error', '')
  emit('status', '')
  try {
    const pendingDefaultPolicyId = defaultPolicyId.value
    const preserveDefaultDraft = defaultDirty.value
    const next = await updateRuntimePolicy(policyId, policyDraft.value)
    applyDocument(next, policyId)
    if (preserveDefaultDraft) defaultPolicyId.value = pendingDefaultPolicyId
    emit('status', `Saved RuntimePolicy ${policyId}`)
  } catch (error) {
    reportError(error)
  } finally {
    savingPolicy.value = false
  }
}

onMounted(reload)
</script>

<template>
  <div class="runtime-policy-settings">
    <section class="runtime-policy-default">
      <div>
        <h2>Workspace default</h2>
        <p>Agent Profiles without an explicit selection resolve to this Policy.</p>
      </div>
      <div class="runtime-policy-default-actions">
        <FormSelect
          v-model="defaultPolicyId"
          class="runtime-policy-default-select"
          :disabled="loading || savingDefault || !document"
          aria-label="Default RuntimePolicy"
        >
          <option
            v-for="policy in document?.policies || []"
            :key="policy.policy_id"
            :value="policy.policy_id"
          >
            {{ policy.policy_id }}
          </option>
        </FormSelect>
        <ActionButton
          variant="primary"
          compact
          :disabled="!defaultDirty || savingDefault"
          @click="saveDefault"
        >
          {{ savingDefault ? 'Applying...' : 'Apply default' }}
        </ActionButton>
        <ActionButton compact :disabled="loading" @click="reload">
          {{ loading ? 'Loading...' : 'Reload' }}
        </ActionButton>
      </div>
    </section>

    <div v-if="document" class="runtime-policy-workspace">
      <nav class="runtime-policy-list" aria-label="RuntimePolicy catalog">
        <button
          v-for="policy in document.policies"
          :key="policy.policy_id"
          type="button"
          :class="{ active: policy.policy_id === selectedPolicyId }"
          @click="selectPolicy(policy.policy_id)"
        >
          <strong>{{ policy.policy_id }}</strong>
          <span>v{{ String(policy.config.version || '') }}</span>
          <small>{{ String(policy.config.description || '') }}</small>
          <em v-if="policy.policy_id === document.default_policy_id">Default</em>
        </button>
      </nav>

      <section v-if="selectedPolicy" class="runtime-policy-editor">
        <header>
          <div>
            <h2>{{ selectedPolicy.policy_id }}</h2>
            <p>{{ selectedPolicy.path }}</p>
          </div>
          <div class="runtime-policy-editor-actions">
            <ActionButton
              variant="primary"
              compact
              :disabled="!policyDirty || savingPolicy"
              @click="savePolicy"
            >
              {{ savingPolicy ? 'Saving...' : 'Save Policy' }}
            </ActionButton>
          </div>
        </header>
        <RuntimePolicyConfigForm
          v-if="policyDraft"
          :data="policyDraft"
          :disabled="savingPolicy"
          @update:data="policyDraft = $event"
        />
      </section>
    </div>

    <div v-else-if="!loading" class="runtime-policy-empty">RuntimePolicy catalog is unavailable.</div>
  </div>
</template>

<style scoped>
.runtime-policy-settings {
  display: grid;
  gap: 16px;
  min-height: 0;
  height: 100%;
}

.runtime-policy-default {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--border-color, #334155);
  border-radius: 12px;
  background: var(--panel-bg, rgba(15, 23, 42, 0.48));
}

.runtime-policy-default h2,
.runtime-policy-editor h2 {
  margin: 0;
  font-size: 16px;
}

.runtime-policy-default p,
.runtime-policy-editor p {
  margin: 4px 0 0;
  color: var(--text-muted, #94a3b8);
  font-size: 12px;
}

.runtime-policy-default-actions,
.runtime-policy-editor-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.runtime-policy-default-select {
  min-width: 180px;
}

.runtime-policy-workspace {
  display: grid;
  grid-template-columns: minmax(190px, 250px) minmax(0, 1fr);
  gap: 14px;
  min-height: 0;
}

.runtime-policy-list {
  display: grid;
  align-content: start;
  gap: 8px;
  overflow: auto;
}

.runtime-policy-list button {
  position: relative;
  display: grid;
  gap: 4px;
  padding: 12px;
  text-align: left;
  border: 1px solid var(--border-color, #334155);
  border-radius: 10px;
  color: inherit;
  background: transparent;
  cursor: pointer;
}

.runtime-policy-list button.active {
  border-color: var(--accent-color, #38bdf8);
  background: rgba(56, 189, 248, 0.08);
}

.runtime-policy-list span,
.runtime-policy-list small {
  color: var(--text-muted, #94a3b8);
}

.runtime-policy-list em {
  position: absolute;
  top: 10px;
  right: 10px;
  color: var(--accent-color, #38bdf8);
  font-size: 11px;
  font-style: normal;
}

.runtime-policy-editor {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
  min-height: 0;
}

.runtime-policy-editor > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.runtime-policy-empty {
  color: var(--text-muted, #94a3b8);
}

@media (max-width: 760px) {
  .runtime-policy-default,
  .runtime-policy-editor > header {
    align-items: stretch;
    flex-direction: column;
  }

  .runtime-policy-default-actions {
    flex-wrap: wrap;
  }

  .runtime-policy-default-select {
    flex: 1 1 180px;
  }

  .runtime-policy-workspace {
    grid-template-columns: 1fr;
  }
}
</style>
