<script setup lang="ts">
import { ref } from 'vue'
import type { MobileNode } from '../api'

defineProps<{
  node: MobileNode
}>()

const emit = defineEmits<{
  (event: 'select', node: MobileNode): void
  (event: 'delete', node: MobileNode): void
  (event: 'trigger', node: MobileNode): void
  (event: 'duplicate', node: MobileNode): void
}>()

const outputExpanded = ref(false)

function nodeStateLabel(node: MobileNode) {
  const state = String(node.state || 'idle')
  if (state === 'working') return '工作中'
  if (state === 'stop') return '已停止'
  return '空闲'
}

function nodeStateClass(node: MobileNode) {
  const state = String(node.state || 'idle')
  if (state === 'working') return 'state-working'
  if (state === 'stop') return 'state-stop'
  return 'state-idle'
}

function selectNode(node: MobileNode) {
  emit('select', node)
}

function deleteNode(node: MobileNode) {
  emit('delete', node)
}

function triggerNode(node: MobileNode) {
  emit('trigger', node)
}

function duplicateNode(node: MobileNode) {
  emit('duplicate', node)
}

function toggleOutput() {
  outputExpanded.value = !outputExpanded.value
}
</script>

<template>
  <div class="node-row">
    <button
      class="node-select"
      type="button"
      @click="selectNode(node)"
    >
      <span class="node-status" :class="nodeStateClass(node)"></span>
      <div class="row-body">
        <div class="row-main">{{ node.name || node.id }}</div>
        <div class="row-sub">{{ node.type_id }} · {{ nodeStateLabel(node) }}</div>
      </div>
      <span v-if="node.pending_count" class="pending-pill">{{ node.pending_count }}</span>
      <span class="row-arrow">›</span>
    </button>
    <div v-if="node.last_message" class="node-output">
      <button
        class="output-toggle"
        type="button"
        :aria-expanded="outputExpanded"
        @click="toggleOutput"
      >
        <span>输出</span>
        <span class="output-toggle-state">
          {{ outputExpanded ? '收起' : '展开' }}
          <span class="output-chevron" :class="{ expanded: outputExpanded }">⌄</span>
        </span>
      </button>
      <div v-if="outputExpanded" class="row-last">{{ node.last_message }}</div>
    </div>
    <div v-if="!node.readonly" class="node-actions">
      <button class="node-action" type="button" @click="triggerNode(node)">Trigger</button>
      <button class="node-action" type="button" @click="duplicateNode(node)">Duplicate</button>
      <button class="node-action danger" type="button" @click="deleteNode(node)">Delete</button>
    </div>
  </div>
</template>

<style scoped>
.node-row {
  width: 100%;
  height: auto;
  min-height: auto;
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  padding: 0;
  text-align: left;
  white-space: normal;
  line-height: 1.35;
  overflow: visible;
  user-select: none;
}

.node-select {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px 12px;
  text-align: left;
  white-space: normal;
  line-height: 1.35;
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
}

.node-select:active {
  border-color: rgba(125, 211, 252, 0.58);
  background: rgba(15, 23, 42, 0.9);
}

.node-select:focus-visible,
.output-toggle:focus-visible,
.node-action:focus-visible {
  outline: 2px solid rgba(56, 189, 248, 0.8);
  outline-offset: 1px;
}

.row-body {
  align-self: stretch;
  flex: 1 1 auto;
  min-width: 0;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow: visible;
}

.row-main,
.row-sub {
  min-width: 0;
  max-width: 100%;
  display: block;
  overflow-wrap: anywhere;
  white-space: normal;
}

.row-main {
  color: rgba(248, 250, 252, 0.96);
  font-weight: 700;
  font-size: 15px;
}

.row-sub {
  color: rgba(148, 163, 184, 0.92);
  font-size: 12px;
}

.row-last {
  padding: 10px 12px 12px;
  color: rgba(203, 213, 225, 0.9);
  font-size: 12px;
  line-height: 1.38;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.node-output {
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.54);
}

.output-toggle {
  width: 100%;
  min-height: 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 12px;
  border: 0;
  background: transparent;
  color: rgba(203, 213, 225, 0.94);
  font-size: 12px;
  font-weight: 700;
  text-align: left;
}

.output-toggle-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: rgba(125, 211, 252, 0.9);
  font-weight: 600;
}

.output-chevron {
  display: inline-block;
  font-size: 16px;
  line-height: 1;
  transform: rotate(0deg);
  transition: transform 0.16s ease;
}

.output-chevron.expanded {
  transform: rotate(180deg);
}

.row-arrow {
  align-self: center;
  flex: 0 0 auto;
  color: rgba(125, 211, 252, 0.88);
  font-size: 24px;
}

.node-status {
  align-self: center;
  flex: 0 0 auto;
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.75);
}

.state-working {
  background: #22c55e;
}

.state-stop {
  background: #f87171;
}

.state-idle {
  background: #38bdf8;
}

.pending-pill {
  align-self: start;
  flex: 0 0 auto;
  min-width: 22px;
  height: 22px;
  padding: 0 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(14, 165, 233, 0.22);
  color: rgba(224, 242, 254, 0.96);
  font-size: 12px;
  font-weight: 700;
}

.node-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.node-action {
  min-width: 0;
  min-height: 40px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid rgba(125, 211, 252, 0.28);
  background: rgba(14, 116, 144, 0.2);
  color: rgba(224, 242, 254, 0.96);
  font-size: 12px;
  font-weight: 700;
}

.node-action.danger {
  border-color: rgba(248, 113, 113, 0.45);
  background: rgba(127, 29, 29, 0.3);
  color: rgba(254, 226, 226, 0.96);
}
</style>
