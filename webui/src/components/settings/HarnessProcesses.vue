<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { controlHarnessProcess, listHarnessProcesses, type HarnessProcess } from '../../harnessApi'
import ActionButton from '../ActionButton.vue'
import { t } from '../../i18n'

const props = defineProps<{ harnessId: string; updating: boolean }>()
const emit = defineEmits<{ openNode: [target: { graphId: string; nodeId: string }] }>()
const processes = ref<HarnessProcess[]>([])
const error = ref('')
const pending = ref(new Set<string>())
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined
const key = (process: HarnessProcess) => JSON.stringify([process.graph_id, process.node_id])
async function refresh() {
  try {
    const result = await listHarnessProcesses(props.harnessId)
    if (!disposed) { processes.value = result.processes; error.value = '' }
  } catch (value) { error.value = value instanceof Error ? value.message : String(value) }
  finally { if (!disposed) timer = setTimeout(refresh, 2000) }
}
async function stop(process: HarnessProcess) {
  pending.value.add(key(process))
  try {
    await controlHarnessProcess(process.node_id, process.graph_id, 'stop')
    processes.value = processes.value.filter(item => key(item) !== key(process))
  } catch (value) { error.value = value instanceof Error ? value.message : String(value) }
  finally { pending.value.delete(key(process)) }
}
onMounted(refresh)
onBeforeUnmount(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>

<template>
  <section class="harness-processes">
    <strong>{{ t('harness.process.list') }} · {{ processes.length }}</strong>
    <p v-if="!processes.length" class="empty">{{ t('harness.process.empty') }}</p>
    <div v-for="process in processes" :key="key(process)" class="process-row">
      <div class="process-info"><b>{{ process.node_id }}</b><small>{{ process.graph_id }} · {{ t(`harness.process.${process.state}`) }}</small></div>
      <div class="process-buttons">
        <ActionButton compact @click="emit('openNode', { graphId: process.graph_id, nodeId: process.node_id })">{{ t('harness.process.openNode') }}</ActionButton>
        <ActionButton compact :disabled="updating || pending.has(key(process)) || process.state === 'stopping'" @click="stop(process)">{{ t('harness.process.stop') }}</ActionButton>
      </div>
      <p v-if="process.error" role="alert">{{ process.error }}</p>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.harness-processes { border-top: 1px solid var(--border-color, #8885); margin-top: 16px; padding-top: 14px; font-size: 13px; }
.process-row { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding: 10px 0; }
.process-info { min-width: 0; flex: 1; overflow-wrap: anywhere; }
.process-buttons { display: flex; flex-wrap: wrap; gap: 6px; }
small { display: block; opacity: .7; margin-top: 4px; }
.empty { opacity: .6; }
[role=alert] { color: #dc6565; width: 100%; overflow-wrap: anywhere; }
</style>
