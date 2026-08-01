<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ActionButton from '../ActionButton.vue'
import FormSelect from '../FormSelect.vue'

import {
  getPasteAgentConfig,
  listAgentProfiles,
  updatePasteAgentConfig,
  type AgentProfile,
} from '../../api'

const profiles = ref<AgentProfile[]>([])
const savedProfileId = ref('')
const selectedProfileId = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const status = ref('')

const agentProfiles = computed(() => profiles.value.filter((profile) => profile.node_type_id === 'agent_node'))
const selectedProfileExists = computed(() => agentProfiles.value.some((profile) => profile.id === selectedProfileId.value))
const dirty = computed(() => selectedProfileId.value !== savedProfileId.value)

function profileLabel(profile: AgentProfile) {
  const name = String(profile.name || '').trim()
  return name && name !== profile.id ? `${name} (${profile.id})` : profile.id
}

async function reload() {
  if (loading.value || saving.value) return
  loading.value = true
  error.value = ''
  status.value = ''
  try {
    const [nextProfiles, config] = await Promise.all([
      listAgentProfiles(),
      getPasteAgentConfig(),
    ])
    profiles.value = nextProfiles
    savedProfileId.value = String(config.profile_id || '').trim()
    selectedProfileId.value = savedProfileId.value
  } catch (cause: any) {
    error.value = String(cause?.message || cause)
  } finally {
    loading.value = false
  }
}

async function refreshProfiles() {
  try {
    profiles.value = await listAgentProfiles()
  } catch (cause: any) {
    error.value = String(cause?.message || cause)
  }
}

async function save() {
  const profileId = selectedProfileId.value.trim()
  if (!profileId || saving.value || !selectedProfileExists.value) return
  saving.value = true
  error.value = ''
  status.value = ''
  try {
    const result = await updatePasteAgentConfig({ profile_id: profileId })
    savedProfileId.value = result.config.profile_id
    selectedProfileId.value = result.config.profile_id
    status.value = `Saved Profile: ${result.config.profile_id}`
  } catch (cause: any) {
    error.value = String(cause?.message || cause)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void reload()
  window.addEventListener('agent-profiles-changed', refreshProfiles)
})

onBeforeUnmount(() => {
  window.removeEventListener('agent-profiles-changed', refreshProfiles)
})
</script>

<template>
  <section class="settings-group">
    <div class="group-head">
      <div>
        <h2>Paste Agent</h2>
        <p>Choose the Agent Profile used when pasted clipboard text or images create a new Agent.</p>
      </div>
      <div class="actions">
        <ActionButton compact :disabled="loading || saving" @click="reload">
          {{ loading ? 'Loading...' : 'Reload' }}
        </ActionButton>
        <ActionButton variant="primary" compact :disabled="loading || saving || !dirty || !selectedProfileExists" @click="save">
          {{ saving ? 'Saving...' : 'Save' }}
        </ActionButton>
      </div>
    </div>

    <label>
      <span>Profile</span>
      <FormSelect v-model="selectedProfileId" :disabled="loading || saving || !agentProfiles.length">
        <option v-if="selectedProfileId && !selectedProfileExists" :value="selectedProfileId">
          Missing Profile: {{ selectedProfileId }}
        </option>
        <option v-for="profile in agentProfiles" :key="profile.id" :value="profile.id">
          {{ profileLabel(profile) }}
        </option>
      </FormSelect>
      <small>The Profile owns provider, prompt, tools, runtime fields, and Runtime Events for the created Agent.</small>
    </label>

    <p v-if="!loading && !agentProfiles.length" class="message error">
      No agent_node Profiles are available. Add one in NodeProfilerEditor first.
    </p>
    <p v-else-if="selectedProfileId && !selectedProfileExists" class="message error">
      The configured Profile no longer exists. Select another Profile and save.
    </p>
    <p v-if="error" class="message error">{{ error }}</p>
    <p v-else-if="status" class="message status">{{ status }}</p>
  </section>
</template>

<style scoped>
.settings-group {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  padding: 12px;
  background: rgba(15, 23, 42, 0.28);
}

.group-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

h2 {
  margin: 0 0 5px;
  font-size: 15px;
}

.group-head p {
  margin: 0;
  color: rgba(148, 163, 184, 0.9);
  font-size: 12px;
  line-height: 1.45;
}

.actions {
  display: flex;
  gap: 7px;
}

label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: rgba(226, 232, 240, 0.94);
  font-size: 12px;
}

label small {
  color: rgba(148, 163, 184, 0.9);
  line-height: 1.45;
}

.message {
  margin: 9px 0 0;
  font-size: 12px;
}

.message.error {
  color: rgba(254, 202, 202, 0.96);
}

.message.status {
  color: rgba(134, 239, 172, 0.96);
}

@media (max-width: 760px) {
  .group-head {
    flex-direction: column;
  }
}
</style>
