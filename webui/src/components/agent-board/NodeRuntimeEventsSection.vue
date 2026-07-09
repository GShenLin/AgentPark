<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  applyRuntimeEventConfig,
  loadRuntimeEventConfig,
  type RuntimeEventConfig,
} from '../../api'
import {
  cloneRuntimeEventConfig,
  deleteRuntimeEventRule,
  ensureCompanionReceiverGroup,
  formatRuntimeApplyErrors,
  makeRuntimeEventRule,
  rulesForNode,
  RUNTIME_EVENT_NAMES,
  setRuntimeEventRule,
} from '../../runtimeEventsConfig'
import type { NodeCard } from './context'

const COMPANION_GROUP_ID = 'companion'

const props = defineProps<{
  node: NodeCard
  graphId: string
}>()

const emit = defineEmits<{
  error: [message: string]
}>()

const loading = ref(false)
const applyingEvent = ref('')
const config = ref<RuntimeEventConfig | null>(null)
const status = ref('')

const nodeRules = computed(() => {
  if (!config.value) return []
  return rulesForNode(config.value, props.graphId, props.node.id)
})
const companionGroup = computed(() => config.value?.receiver_groups?.[COMPANION_GROUP_ID] || null)

function showError(message: string) {
  emit('error', message)
}

function profileForEvent(event: string) {
  return String(companionGroup.value?.event_profiles?.[event] || '')
}

function routeForEvent(event: string) {
  return nodeRules.value.find(({ rule, event: itemEvent }) => {
    return itemEvent === event && rule.action === 'node.dispatch' && rule.target === COMPANION_GROUP_ID
  }) || null
}

function eventEnabled(event: string) {
  return routeForEvent(event)?.rule.enabled !== false && Boolean(routeForEvent(event))
}

function canEnableEvent(event: string) {
  return Boolean(profileForEvent(event))
}

async function refreshEvents() {
  loading.value = true
  showError('')
  status.value = ''
  try {
    const document = await loadRuntimeEventConfig()
    config.value = cloneRuntimeEventConfig(document.config)
  } catch (error: any) {
    showError(String(error?.message || error))
  } finally {
    loading.value = false
  }
}

async function applyConfig(next: RuntimeEventConfig, message: string, event: string) {
  applyingEvent.value = event
  showError('')
  status.value = ''
  try {
    const result = await applyRuntimeEventConfig(next)
    if (!result.ok) {
      throw new Error(formatRuntimeApplyErrors(result.errors))
    }
    config.value = cloneRuntimeEventConfig(next)
    status.value = message
  } catch (error: any) {
    showError(String(error?.message || error))
  } finally {
    applyingEvent.value = ''
  }
}

async function setEventEnabled(event: string, enabled: boolean) {
  if (!config.value) return
  if (enabled && !canEnableEvent(event)) {
    showError(`Set a Companion profile for ${event} in Settings first.`)
    return
  }
  const next = cloneRuntimeEventConfig(config.value)
  const existing = routeForEvent(event)
  if (enabled) {
    ensureCompanionReceiverGroup(next, COMPANION_GROUP_ID, event, profileForEvent(event))
    if (existing) {
      setRuntimeEventRule(next, {
        graphId: props.graphId,
        nodeId: props.node.id,
        event,
        rule: { ...existing.rule, enabled: true },
      })
    } else {
      setRuntimeEventRule(next, {
        graphId: props.graphId,
        nodeId: props.node.id,
        event,
        rule: makeRuntimeEventRule({
          event,
          action: 'node.dispatch',
          target: COMPANION_GROUP_ID,
        }),
      })
    }
  } else if (existing) {
    deleteRuntimeEventRule(next, {
      graphId: props.graphId,
      nodeId: props.node.id,
      event,
    })
  }
  await applyConfig(next, enabled ? `${event} enabled` : `${event} disabled`, event)
}

watch(
  () => [props.graphId, props.node.id],
  () => {
    refreshEvents()
  },
)

onMounted(refreshEvents)
</script>

<template>
  <section class="runtime-events-section">
    <div class="section-head">
      <div class="section-title">Runtime Events</div>
      <button class="mini-btn" type="button" :disabled="loading || !!applyingEvent" @click="refreshEvents">
        {{ loading ? 'Loading...' : 'Reload' }}
      </button>
    </div>

    <div v-if="status" class="event-status">{{ status }}</div>
    <div v-if="loading" class="empty-hint">Loading runtime event config...</div>

    <div v-else class="event-toggle-list">
      <label v-for="event in RUNTIME_EVENT_NAMES" :key="event" class="event-toggle-row">
        <input
          :checked="eventEnabled(event)"
          type="checkbox"
          :disabled="!!applyingEvent || (!eventEnabled(event) && !canEnableEvent(event))"
          @change="setEventEnabled(event, ($event.target as HTMLInputElement).checked)"
        />
        <span class="event-name">{{ event }}</span>
        <span class="event-profile">{{ profileForEvent(event) || 'Set profile in Settings' }}</span>
        <span v-if="applyingEvent === event" class="event-state">Applying...</span>
      </label>
    </div>
  </section>
</template>

<style scoped>
.runtime-events-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 0 0 auto;
  border-top: 1px solid rgba(148, 163, 184, 0.2);
  padding-top: 12px;
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

.event-toggle-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.event-toggle-row {
  display: grid;
  grid-template-columns: auto minmax(98px, 0.8fr) minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  padding: 8px;
}

.event-name {
  color: #bfdbfe;
  font-family: Consolas, Menlo, monospace;
  font-size: 12px;
}

.event-profile,
.event-state {
  min-width: 0;
  color: rgba(226, 232, 240, 0.86);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.event-state {
  color: #99f6e4;
}

.mini-btn {
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.92);
  color: #f8fafc;
  cursor: pointer;
  padding: 6px 9px;
  font-size: 12px;
  text-decoration: none;
  white-space: nowrap;
}

.mini-btn:disabled,
input:disabled {
  cursor: default;
  opacity: 0.55;
}

.empty-hint {
  font-size: 12px;
  color: rgba(148, 163, 184, 0.84);
}

.event-status {
  border: 1px solid rgba(45, 212, 191, 0.24);
  border-radius: 8px;
  background: rgba(15, 118, 110, 0.14);
  color: #ccfbf1;
  font-size: 12px;
  line-height: 1.35;
  overflow-wrap: anywhere;
  padding: 8px 10px;
}
</style>
