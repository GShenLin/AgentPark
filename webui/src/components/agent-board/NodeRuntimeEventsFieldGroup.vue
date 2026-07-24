<script setup lang="ts">
import { ref, watch } from 'vue'
import NodeRuntimeEventsSection from './NodeRuntimeEventsSection.vue'
import type { NodeCard } from './context'

const props = defineProps<{
  node: Pick<NodeCard, 'id'>
  graphId: string
}>()

const emit = defineEmits<{
  error: [message: string]
}>()

const expanded = ref(false)

function onToggle(event: Event) {
  const target = event.currentTarget
  if (!(target instanceof HTMLDetailsElement)) return
  expanded.value = target.open
}

watch(
  () => [props.graphId, props.node.id],
  () => {
    expanded.value = false
  },
  { immediate: true },
)
</script>

<template>
  <details class="runtime-events-field-group" :open="expanded" @toggle="onToggle">
    <summary class="runtime-events-field-group-summary">
      <span>Event</span>
      <span class="runtime-events-field-group-chevron" aria-hidden="true">›</span>
    </summary>
    <div class="runtime-events-field-group-content">
      <NodeRuntimeEventsSection
        v-if="expanded"
        :node="node"
        :graph-id="graphId"
        @error="emit('error', $event)"
      />
    </div>
  </details>
</template>

<style scoped>
.runtime-events-field-group {
  flex: 0 0 auto;
  border: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.22));
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.28);
  overflow: hidden;
}

.runtime-events-field-group-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  color: var(--theme-panel-node-side-editor-text-secondary, #cbd5e1);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  list-style: none;
  user-select: none;
}

.runtime-events-field-group-summary::-webkit-details-marker {
  display: none;
}

.runtime-events-field-group-summary:hover {
  background: rgba(148, 163, 184, 0.08);
}

.runtime-events-field-group-chevron {
  color: rgba(148, 163, 184, 0.82);
  font-size: 18px;
  line-height: 1;
  transition: transform 0.16s ease;
}

.runtime-events-field-group[open] .runtime-events-field-group-chevron {
  transform: rotate(90deg);
}

.runtime-events-field-group-content {
  padding: 2px 12px 12px;
}

.runtime-events-field-group-content :deep(.runtime-events-section) {
  border-top: 0;
  padding-top: 0;
}
</style>
