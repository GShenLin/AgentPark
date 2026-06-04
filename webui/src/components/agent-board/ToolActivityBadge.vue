<script setup lang="ts">
import { computed } from 'vue'
import type { RuntimeEvent, RuntimeToolCall } from '../../api'
import { buildRuntimeToolCallViews, latestRuntimeNotice } from './toolRuntimeEvents'

const props = defineProps<{
  event?: RuntimeEvent | null
  events?: RuntimeEvent[]
  calls?: RuntimeToolCall[]
}>()

const activity = computed(() => {
  const event = props.event
  if (event?.type === 'runtime_notice') {
    return { label: 'Working', name: event.message, tone: 'running' }
  }
  const views = buildRuntimeToolCallViews(props.calls, props.events)
  const notice = latestRuntimeNotice(props.events)
  if (views.length || !event) {
    const last = views[views.length - 1]
    if (!last) {
      if (!notice) return null
      return { label: 'Working', name: notice.message, tone: 'running' }
    }
    const label = views.length > 1 ? `${views.length} tools` : last.status === 'completed' ? 'Used' : last.status || 'Used'
    return { label, name: last.name, tone: last.tone }
  }
  const name = String(event.name || 'tool').trim() || 'tool'
  if (event.type === 'tool_call_start') {
    return { label: 'Running', name, tone: 'running' }
  }
  const status = String(event.status || 'completed').trim().toLowerCase()
  const label = status === 'completed' ? 'Done' : status || 'Done'
  return { label, name, tone: status === 'completed' ? 'done' : 'attention' }
})
</script>

<template>
  <div v-if="activity" class="tool-activity" :class="`tone-${activity.tone}`">
    <span class="tool-dot"></span>
    <span class="tool-label">{{ activity.label }}</span>
    <span class="tool-name">{{ activity.name }}</span>
  </div>
</template>

<style scoped>
.tool-activity {
  min-height: 22px;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  padding: 3px 6px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.42);
  color: rgba(226, 232, 240, 0.78);
  font-size: 10px;
  overflow: hidden;
}

.tool-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  flex: 0 0 auto;
  background: rgba(125, 211, 252, 0.95);
}

.tool-label {
  flex: 0 0 auto;
  color: rgba(203, 213, 225, 0.82);
}

.tool-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(255, 255, 255, 0.86);
  font-family: monospace;
}

.tool-activity.tone-done .tool-dot {
  background: rgba(52, 211, 153, 0.95);
}

.tool-activity.tone-attention .tool-dot {
  background: rgba(251, 191, 36, 0.95);
}

.tool-activity.tone-running .tool-dot {
  animation: tool-pulse 1s ease-in-out infinite;
}

@keyframes tool-pulse {
  0%,
  100% {
    opacity: 0.45;
  }
  50% {
    opacity: 1;
  }
}
</style>
