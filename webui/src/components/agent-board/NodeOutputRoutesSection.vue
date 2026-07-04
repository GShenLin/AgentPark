<script setup lang="ts">
import { computed, inject } from 'vue'
import { AgentBoardKey, type NodeCard } from './context'

const props = defineProps<{
  node: NodeCard
}>()

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx = injected

const routes = computed(() => ctx.links.value.filter((link) => link.from.node === props.node.id))
const targetOptions = computed(() => ctx.nodes.value.filter((node) => node.id !== props.node.id))

function outputOptions(count: number) {
  return Array.from({ length: Math.max(1, count) }, (_, index) => index)
}

function inputOptions(nodeId: string) {
  const target = ctx.nodes.value.find((node) => node.id === nodeId)
  const count = Math.max(1, Number(target?.inputNum || 1))
  return outputOptions(count)
}

function targetDisplayName(nodeId: string) {
  const target = ctx.nodes.value.find((node) => node.id === nodeId)
  return String(target?.name || nodeId)
}

function setOutput(routeId: string, value: string) {
  ctx.updateOutputRoute(routeId, { outputIndex: Number(value) }).catch(() => null)
}

function setTarget(routeId: string, value: string) {
  ctx.updateOutputRoute(routeId, { targetNodeId: value, inputIndex: 0 }).catch(() => null)
}

function setInput(routeId: string, value: string) {
  ctx.updateOutputRoute(routeId, { inputIndex: Number(value) }).catch(() => null)
}
</script>

<template>
  <section class="route-section">
    <div class="route-head">
      <div class="route-title">Output Routes</div>
    </div>

    <div v-if="routes.length" class="route-list">
      <div v-for="route in routes" :key="route.id" class="route-row">
        <label>
          <span>Output</span>
          <select :value="route.from.index" @change="setOutput(route.id, ($event.target as HTMLSelectElement).value)">
            <option v-for="index in outputOptions(node.outputNum)" :key="index" :value="index">{{ index }}</option>
          </select>
        </label>
        <label>
          <span>Target</span>
          <select
            class="target-select"
            :value="route.to.node"
            :title="targetDisplayName(route.to.node)"
            @change="setTarget(route.id, ($event.target as HTMLSelectElement).value)"
          >
            <option v-for="target in targetOptions" :key="target.id" :value="target.id">
              {{ target.name || target.id }}
            </option>
          </select>
        </label>
        <label>
          <span>Input</span>
          <select :value="route.to.index" @change="setInput(route.id, ($event.target as HTMLSelectElement).value)">
            <option v-for="index in inputOptions(route.to.node)" :key="index" :value="index">{{ index }}</option>
          </select>
        </label>
        <button type="button" class="route-icon-btn danger" title="Remove route" @click="ctx.removeOutputRoute(route.id).catch(() => null)">x</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.route-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.route-title {
  color: #f8fafc;
  font-size: 13px;
  font-weight: 700;
}

.route-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.9);
  color: #e2e8f0;
  font-size: 17px;
  font-weight: 700;
  line-height: 1;
  text-align: center;
  cursor: pointer;
}

.route-row .route-icon-btn {
  width: 24px;
  height: 20px;
}

.route-icon-btn.danger {
  color: #fecaca;
  font-size: 14px;
  border-color: rgba(248, 113, 113, 0.35);
  background: rgba(127, 29, 29, 0.24);
}

.route-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.route-row {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) 38px 24px;
  gap: 6px;
  align-items: end;
}

label {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

span {
  color: rgba(148, 163, 184, 0.9);
  font-size: 10px;
  line-height: 1;
  text-align: center;
}

select {
  width: 100%;
  min-width: 0;
  height: 20px;
  padding: 0 4px;
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.92);
  color: #f8fafc;
  font-size: 11px;
  line-height: 20px;
  text-align: center;
  text-align-last: center;
}

.target-select {
  overflow: hidden;
  text-overflow: ellipsis;
}

</style>
