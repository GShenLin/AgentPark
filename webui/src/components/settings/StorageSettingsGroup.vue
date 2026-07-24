<script setup lang="ts">
import { ref } from 'vue'

import { clearLogs } from '../../settingsApi'

const props = defineProps<{
  memoriesPath: string
  runtime?: {
    active_memories_root?: string
    configured_memories_root?: string
  }
}>()

const emit = defineEmits<{
  'update:memoriesPath': [value: string]
}>()

const clearing = ref(false)
const clearStatus = ref('')
const clearError = ref('')

async function handleClearLogs() {
  if (clearing.value) return
  const activeRoot = String(props.runtime?.active_memories_root || '').trim()
  const targetLabel = activeRoot || 'the active memories directory'
  const confirmed = window.confirm(
    `Clear generated logs under ${targetLabel}?\n\nNode configuration, messages, memories, and generated assets are preserved.`,
  )
  if (!confirmed) return

  clearing.value = true
  clearStatus.value = ''
  clearError.value = ''
  try {
    const result = await clearLogs()
    const lines = String(result.stdout || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    clearStatus.value = lines[lines.length - 1] || 'Logs cleared.'
  } catch (error: any) {
    clearError.value = String(error?.message || error)
  } finally {
    clearing.value = false
  }
}
</script>

<template>
  <section class="settings-group storage-group">
    <div class="storage-heading">
      <h2>Storage</h2>
      <button type="button" class="clear-logs" :disabled="clearing" @click="handleClearLogs">
        {{ clearing ? 'Clearing...' : 'Clear Logs' }}
      </button>
    </div>
    <div class="form-grid">
      <label>
        <span>Memories Directory</span>
        <input
          :value="memoriesPath"
          placeholder="C:\\AgentPark\\memories"
          @input="emit('update:memoriesPath', ($event.target as HTMLInputElement).value)"
        />
        <small>Saved locally in .cache/memoryLocalConfig.json.</small>
        <small>Only absolute paths take effect. Invalid values fall back to the project's memories directory after restart.</small>
        <small v-if="props.runtime?.active_memories_root">Active: {{ props.runtime.active_memories_root }}</small>
        <small
          v-if="props.runtime?.configured_memories_root && props.runtime.configured_memories_root !== props.runtime.active_memories_root"
          class="pending-path"
        >
          After restart: {{ props.runtime.configured_memories_root }}
        </small>
        <small>Clear Logs removes runtime event logs, response payload logs, their backups, and HTTP debug dumps.</small>
        <small v-if="clearStatus" class="clear-status" role="status">{{ clearStatus }}</small>
        <small v-if="clearError" class="clear-error" role="alert">{{ clearError }}</small>
      </label>
    </div>
  </section>
</template>

<style scoped>
.storage-group {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  padding: 12px;
  background: rgba(15, 23, 42, 0.28);
}

.storage-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.storage-heading h2 {
  margin: 0 0 10px;
  font-size: 15px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 1fr));
  gap: 12px;
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

label small.pending-path {
  color: rgba(250, 204, 21, 0.92);
}

input {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  padding: 8px 9px;
  color: rgba(226, 232, 240, 0.96);
  background: rgba(2, 6, 23, 0.5);
  font: inherit;
}

.clear-logs {
  flex: 0 0 auto;
  border: 1px solid rgba(248, 113, 113, 0.42);
  border-radius: 8px;
  padding: 7px 12px;
  color: rgba(254, 202, 202, 0.98);
  background: rgba(127, 29, 29, 0.2);
  cursor: pointer;
}

.clear-logs:hover:not(:disabled) {
  border-color: rgba(248, 113, 113, 0.72);
  background: rgba(153, 27, 27, 0.3);
}

.clear-logs:disabled {
  cursor: wait;
  opacity: 0.58;
}

.clear-status {
  color: rgba(134, 239, 172, 0.96);
}

.clear-error {
  color: rgba(253, 164, 175, 0.98);
}

@media (max-width: 1120px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
