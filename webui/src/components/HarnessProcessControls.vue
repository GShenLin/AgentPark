<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import ActionButton from './ActionButton.vue'
import { controlHarnessProcess, getHarnessProcess, type HarnessProcess } from '../harnessApi'
import { t } from '../i18n'

const props = defineProps<{ nodeId: string; graphId: string }>()
const state = ref<HarnessProcess | null>(null)
const error = ref('')
const pending = ref<'start' | 'stop' | ''>('')
let disposed = false
let generation = 0
let actionGeneration = 0
let timer: ReturnType<typeof setTimeout> | undefined

async function refresh(version: number) {
  try {
    const result = await getHarnessProcess(props.nodeId, props.graphId)
    if (!disposed && version === generation) { state.value = result; error.value = '' }
  } catch (value) {
    if (!disposed && version === generation) error.value = value instanceof Error ? value.message : String(value)
  } finally {
    if (!disposed && version === generation) timer = setTimeout(() => refresh(version), 2000)
  }
}
async function act(action: 'start' | 'stop') {
  pending.value = action
  error.value = ''
  const version = generation
  const actionVersion = ++actionGeneration
  try {
    const result = await controlHarnessProcess(props.nodeId, props.graphId, action)
    if (!disposed && version === generation && actionVersion === actionGeneration) state.value = result
  } catch (value) {
    if (!disposed && version === generation && actionVersion === actionGeneration) error.value = value instanceof Error ? value.message : String(value)
  } finally { if (version === generation && actionVersion === actionGeneration) pending.value = '' }
}
watch(() => [props.nodeId, props.graphId], () => {
  generation++
  if (timer) clearTimeout(timer)
  state.value = null
  pending.value = ''
  void refresh(generation)
}, { immediate: true })
onBeforeUnmount(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>

<template>
  <div class="harness-process-controls">
    <div class="process-actions">
      <span role="status">{{ t('harness.process.label') }} · {{ state ? t(`harness.process.${state.state}`) : t('harness.checking') }}</span>
      <ActionButton v-if="!state || ['stopped', 'error'].includes(state.state)" compact
        :disabled="!state || !!pending" :title="t('harness.process.startHint')" @pointerdown.stop @click.stop="act('start')">
        {{ pending === 'start' ? t('harness.process.starting') : t('harness.process.start') }}
      </ActionButton>
      <ActionButton v-else compact :disabled="pending === 'stop' || state.state === 'stopping'"
        :title="t('harness.process.stopHint')" @pointerdown.stop @click.stop="act('stop')">
        {{ pending === 'stop' ? t('harness.process.stopping') : t('harness.process.stop') }}
      </ActionButton>
    </div>
    <p v-if="error || state?.error" role="alert">{{ error || state?.error }}</p>
  </div>
</template>

<style scoped>
.harness-process-controls { margin: 4px 12px 8px; font-size: 12px; min-width: 0; }
.process-actions { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
p { color: var(--danger-color, #dc6565); overflow-wrap: anywhere; margin: 6px 0 0; }
</style>
