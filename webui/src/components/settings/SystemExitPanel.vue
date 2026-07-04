<script setup lang="ts">
import { ref } from 'vue'
import { exitServer } from '../../api'

const exiting = ref(false)
const status = ref('')
const error = ref('')

async function requestExit() {
  if (exiting.value) return
  const confirmed = window.confirm('Exit AgentPark backend?')
  if (!confirmed) return
  exiting.value = true
  status.value = ''
  error.value = ''
  try {
    await exitServer()
    status.value = 'Exit requested'
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to exit backend')
    exiting.value = false
  }
}
</script>

<template>
  <div class="system-exit-panel">
    <section class="exit-section">
      <h2>Exit</h2>
      <button class="exit-button" type="button" :disabled="exiting" @click="requestExit">
        {{ exiting ? 'Exiting...' : 'Exit backend' }}
      </button>
      <div v-if="status" class="exit-status">{{ status }}</div>
      <div v-if="error" class="exit-error">{{ error }}</div>
    </section>
  </div>
</template>

<style scoped>
.system-exit-panel {
  flex: 1;
  min-height: 0;
  padding: 20px;
  background: var(--bg-primary);
}

.exit-section {
  max-width: 520px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 18px;
  background: var(--bg-secondary);
}

.exit-section h2 {
  margin: 0 0 16px;
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 600;
}

.exit-button {
  min-height: 34px;
  border: 1px solid rgba(239, 68, 68, 0.45);
  border-radius: 6px;
  padding: 8px 14px;
  color: #fecaca;
  background: rgba(127, 29, 29, 0.35);
  font-size: 13px;
  font-weight: 600;
}

.exit-button:hover:not(:disabled) {
  background: rgba(185, 28, 28, 0.42);
}

.exit-button:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.exit-status,
.exit-error {
  margin-top: 14px;
  font-size: 13px;
}

.exit-status {
  color: #86efac;
}

.exit-error {
  color: #fca5a5;
}
</style>
