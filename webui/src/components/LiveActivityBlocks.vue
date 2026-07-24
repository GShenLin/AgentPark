<script setup lang="ts">
import { ref } from 'vue'
import { stopNodeToolCall, type LiveActivityBlock } from '../api'

const props = defineProps<{
  blocks: LiveActivityBlock[]
  nodeId?: string
  graphId?: string
}>()

const stoppingCalls = ref<Record<string, boolean>>({})
const stopErrors = ref<Record<string, string>>({})

function normalizedStatus(block: LiveActivityBlock) {
  return String(block.status || '').trim().toLowerCase()
}

function canStop(block: LiveActivityBlock) {
  const callId = String(block.call_id || '').trim()
  const status = normalizedStatus(block)
  return (
    block.type === 'tool_call' &&
    !!callId &&
    !!String(props.nodeId || '').trim() &&
    !!String(props.graphId || '').trim() &&
    (status === 'running' || status === 'in_progress')
  )
}

function argumentsText(block: LiveActivityBlock) {
  if (!block.arguments || typeof block.arguments !== 'object') return ''
  try {
    return JSON.stringify(block.arguments, null, 2)
  } catch {
    return String(block.arguments)
  }
}

async function stopCall(block: LiveActivityBlock) {
  const callId = String(block.call_id || '').trim()
  const nodeId = String(props.nodeId || '').trim()
  const graphId = String(props.graphId || '').trim()
  if (!callId || !nodeId || !graphId || stoppingCalls.value[callId]) return

  stoppingCalls.value = { ...stoppingCalls.value, [callId]: true }
  const nextErrors = { ...stopErrors.value }
  delete nextErrors[callId]
  stopErrors.value = nextErrors
  try {
    await stopNodeToolCall(nodeId, graphId, callId)
  } catch (error) {
    const nextStopping = { ...stoppingCalls.value }
    delete nextStopping[callId]
    stoppingCalls.value = nextStopping
    stopErrors.value = {
      ...stopErrors.value,
      [callId]: String((error as Error)?.message || error),
    }
  }
}
</script>

<template>
  <section
    v-for="block in blocks"
    :key="block.id"
    class="live-activity-block"
    :class="`activity-${block.type}`"
  >
    <div v-if="block.type === 'web_search'" class="live-activity-web-searching">
      <span>Web Searching</span><span v-if="block.text">&nbsp;{{ block.text }}</span>
    </div>
    <div v-else class="live-activity-head">
      <span class="live-activity-label">{{ block.label }}</span>
      <span class="live-activity-actions">
        <span class="live-activity-status">{{ stoppingCalls[String(block.call_id || '')] ? 'stopping' : block.status }}</span>
        <button
          v-if="canStop(block)"
          type="button"
          class="live-activity-stop"
          :disabled="!!stoppingCalls[String(block.call_id || '')]"
          @click="stopCall(block)"
        >
          {{ stoppingCalls[String(block.call_id || '')] ? 'Stopping…' : 'Stop' }}
        </button>
      </span>
    </div>
    <pre v-if="block.type === 'tool_call' && argumentsText(block)" class="live-activity-arguments">{{ argumentsText(block) }}</pre>
    <div v-if="block.type !== 'web_search' && block.text" class="live-activity-body">{{ block.text }}</div>
    <div v-if="block.type !== 'web_search' && block.sources?.length" class="live-activity-sources">
      <a
        v-for="(source, index) in block.sources"
        :key="`${block.id}-${index}`"
        :href="source.url"
        target="_blank"
        rel="noreferrer noopener"
      >
        {{ source.title || source.url || `Source ${index + 1}` }}
      </a>
    </div>
    <div v-if="stopErrors[String(block.call_id || '')]" class="live-activity-error">
      {{ stopErrors[String(block.call_id || '')] }}
    </div>
  </section>
</template>

<style scoped>
.live-activity-block {
  border-top: 1px solid rgba(125, 211, 252, 0.16);
  background: rgba(30, 41, 59, 0.22);
}

.live-activity-block.activity-web_search { background: rgba(6, 78, 59, 0.18); }
.live-activity-block.activity-file_search { background: rgba(49, 46, 129, 0.16); }
.live-activity-block.activity-image_generation { background: rgba(88, 28, 135, 0.16); }
.live-activity-block.activity-refusal { background: rgba(127, 29, 29, 0.18); }
.live-activity-block.activity-tool_call { background: rgba(83, 22, 54, 0.16); }

.live-activity-web-searching {
  padding: 8px 10px;
  color: rgba(125, 211, 252, 0.92);
  font-size: 11px;
  font-weight: 700;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.live-activity-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px 0;
}

.live-activity-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(125, 211, 252, 0.88);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 11px;
  font-weight: 700;
}

.live-activity-actions {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex: 0 0 auto;
}

.live-activity-status {
  color: rgba(148, 163, 184, 0.92);
  font-size: 11px;
}

.live-activity-stop {
  min-height: 26px;
  border: 1px solid rgba(248, 113, 113, 0.5);
  border-radius: 6px;
  padding: 3px 9px;
  color: rgba(254, 226, 226, 0.96);
  background: rgba(127, 29, 29, 0.52);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}

.live-activity-stop:hover:not(:disabled) { background: rgba(185, 28, 28, 0.68); }
.live-activity-stop:disabled { opacity: 0.6; cursor: wait; }

.live-activity-body {
  padding: 9px 10px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.5;
  color: rgba(226, 232, 240, 0.96);
  font-size: 14px;
}

.live-activity-arguments {
  margin: 8px 10px 0;
  padding: 7px 8px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 7px;
  color: rgba(203, 213, 225, 0.9);
  background: rgba(2, 6, 23, 0.38);
  font-size: 11px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  overflow: auto;
}

.live-activity-sources {
  display: grid;
  gap: 4px;
  padding: 0 10px 10px;
}

.live-activity-sources a {
  color: rgba(125, 211, 252, 0.92);
  overflow-wrap: anywhere;
}

.live-activity-error {
  padding: 6px 10px 9px;
  color: rgba(254, 202, 202, 0.96);
  font-size: 11px;
  overflow-wrap: anywhere;
}
</style>
