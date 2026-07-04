<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { launchNodeDesktopPet, listNodeDesktopViews, type NodeDesktopView } from './api'

const params = new URLSearchParams(window.location.search)
const workingPath = ref(String(params.get('working_path') || '').trim())
const targetPath = ref(String(params.get('target_path') || params.get('working_path') || '').trim())
const views = ref<NodeDesktopView[]>([])
const loading = ref(false)
const launchingViewId = ref('')
const error = ref('')
const completed = ref(false)

const runningViews = computed(() => {
  return views.value.filter((view) => view.visible !== false)
})

function viewTitle(view: NodeDesktopView) {
  return String(view.node?.name || view.node_id || 'Pet').trim()
}

function viewMeta(view: NodeDesktopView) {
  const path = String(view.node?.working_path || '').trim()
  return path || `${view.graph_id} / ${view.node_id}`
}

async function refreshViews() {
  loading.value = true
  error.value = ''
  try {
    const nextViews = await listNodeDesktopViews()
    views.value = nextViews
    const candidates = nextViews.filter((view) => view.visible !== false)
    const onlyCandidate = candidates.length === 1 ? candidates[0] : null
    if (onlyCandidate && targetPath.value) {
      await choosePet(onlyCandidate)
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to load Pets')
  } finally {
    loading.value = false
  }
}

async function choosePet(view: NodeDesktopView) {
  if (!targetPath.value || launchingViewId.value) return
  launchingViewId.value = view.view_id
  error.value = ''
  completed.value = false
  try {
    const payload: Parameters<typeof launchNodeDesktopPet>[0] = {
      graph_id: view.graph_id,
      node_id: view.node_id,
      visible: true,
      pinned: view.pinned,
      open_chat: true,
      draft_prefix: `${targetPath.value}\n`,
    }
    if (workingPath.value) {
      payload.working_path = workingPath.value
    }
    await launchNodeDesktopPet(payload)
    completed.value = true
    closePickerWindow()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to open Pet')
  } finally {
    launchingViewId.value = ''
  }
}

function closePickerWindow() {
  window.close()
  window.setTimeout(() => {
    if (!window.closed) {
      window.location.replace('about:blank')
    }
  }, 250)
}

onMounted(() => {
  document.title = 'AgentPark Ask Here'
  void refreshViews()
})
</script>

<template>
  <main class="pet-picker">
    <section class="picker-panel">
      <header class="picker-header">
        <div>
          <h1>Ask Here</h1>
          <p :title="targetPath">{{ targetPath || 'No target path provided' }}</p>
        </div>
        <button class="picker-button" type="button" :disabled="loading" @click="refreshViews">
          {{ loading ? 'Refreshing' : 'Refresh' }}
        </button>
      </header>

      <div v-if="error" class="picker-error">{{ error }}</div>
      <div v-if="completed" class="picker-empty">Opened.</div>
      <div v-if="loading" class="picker-empty">Loading Pets...</div>
      <div v-else-if="runningViews.length === 0" class="picker-empty">
        No running Pet found. Open a Pet from AgentPark first, then use Ask Here again.
      </div>
      <div v-else class="pet-list">
        <button
          v-for="view in runningViews"
          :key="view.view_id"
          class="pet-row"
          type="button"
          :disabled="!targetPath || !!launchingViewId"
          @click="choosePet(view)"
        >
          <span>
            <strong>{{ viewTitle(view) }}</strong>
            <small>{{ viewMeta(view) }}</small>
          </span>
          <em>{{ launchingViewId === view.view_id ? 'Opening' : 'Choose' }}</em>
        </button>
      </div>
    </section>
  </main>
</template>

<style scoped>
.pet-picker {
  min-height: 100vh;
  display: flex;
  align-items: stretch;
  justify-content: center;
  padding: 24px;
  background: #09111f;
  color: rgba(226, 232, 240, 0.96);
}

.picker-panel {
  width: min(760px, 100%);
  margin: auto;
}

.picker-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.22);
}

.picker-header h1 {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 700;
}

.picker-header p {
  margin: 0;
  max-width: 560px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(148, 163, 184, 0.95);
  font-size: 13px;
}

.picker-button,
.pet-row {
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(15, 23, 42, 0.78);
  color: rgba(226, 232, 240, 0.96);
}

.picker-button {
  border-radius: 7px;
  padding: 7px 12px;
  cursor: pointer;
}

.picker-button:disabled,
.pet-row:disabled {
  cursor: progress;
  opacity: 0.6;
}

.picker-error,
.picker-empty {
  margin-top: 18px;
  padding: 14px 0;
  color: rgba(203, 213, 225, 0.92);
}

.picker-error {
  color: #fecaca;
}

.pet-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 18px;
}

.pet-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-height: 62px;
  border-radius: 8px;
  padding: 10px 12px;
  text-align: left;
  cursor: pointer;
}

.pet-row:hover:not(:disabled) {
  background: rgba(14, 116, 144, 0.22);
}

.pet-row span {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
}

.pet-row strong,
.pet-row small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pet-row small {
  color: rgba(148, 163, 184, 0.95);
  font-size: 12px;
}

.pet-row em {
  flex-shrink: 0;
  font-style: normal;
  color: rgba(125, 211, 252, 0.95);
}
</style>
