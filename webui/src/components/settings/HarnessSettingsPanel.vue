<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import ActionButton from '../ActionButton.vue'
import { t } from '../../i18n'
import { checkHarness, getHarnessJob, listHarnesses, operateHarness, type HarnessInfo, type HarnessJob } from '../../harnessApi'

const harnesses = ref<HarnessInfo[]>([])
const jobs = ref<Record<string, HarnessJob>>({})
const pending = ref<Record<string, boolean>>({})
const error = ref('')
const loading = ref(false)
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined

function showError(value: unknown) {
  error.value = value instanceof Error ? value.message : String(value)
}
function update(value: HarnessInfo) {
  harnesses.value = harnesses.value.map(item => item.id === value.id ? value : item)
}
function schedulePoll() {
  if (timer) clearTimeout(timer)
  if (!disposed && Object.values(jobs.value).some(job => job.status === 'running')) timer = setTimeout(poll, 1500)
}
async function poll() {
  try {
    for (const job of Object.values(jobs.value).filter(item => item.status === 'running')) {
      const next = await getHarnessJob(job.id)
      if (disposed) return
      jobs.value[job.harness_id] = next
      if (next.status !== 'running') {
        if (next.harness) update(next.harness)
        update(await checkHarness(job.harness_id))
      }
    }
  } catch (value) { showError(value) }
  finally { schedulePoll() }
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await listHarnesses()
    if (disposed) return
    harnesses.value = result.harnesses
    jobs.value = Object.fromEntries(result.jobs.map(job => [job.harness_id, job]))
    schedulePoll()
  } catch (value) { showError(value) }
  finally { loading.value = false }
}
async function act(id: string, action: 'check' | HarnessJob['action']) {
  pending.value[id] = true
  error.value = ''
  try {
    if (action === 'check') update(await checkHarness(id))
    else {
      jobs.value[id] = await operateHarness(id, action)
      schedulePoll()
    }
  } catch (value) { showError(value) }
  finally { pending.value[id] = false }
}
function busy(id: string) { return pending.value[id] || jobs.value[id]?.status === 'running' }
onMounted(load)
onBeforeUnmount(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>

<template>
  <section class="harness-settings">
    <div class="harness-toolbar">
      <p>{{ t('harness.description') }}</p>
      <ActionButton compact :disabled="loading" @click="load">{{ t('settings.reload') }}</ActionButton>
    </div>
    <p class="harness-note">{{ t('harness.installNote') }}</p>
    <p v-if="error" role="alert" class="harness-error">{{ error }}</p>
    <p v-if="loading">{{ t('harness.checking') }}</p>
    <div class="harness-grid">
      <article v-for="item in harnesses" :key="item.id" class="harness-card">
        <div class="harness-title">
          <a :href="item.homepage" target="_blank" rel="noopener noreferrer">{{ item.name }}</a>
          <span :class="['harness-status', item.status]">{{ busy(item.id) ? t('harness.running') : t(`harness.status.${item.status}`) }}</span>
        </div>
        <dl>
          <dt>{{ t('harness.version') }}</dt><dd>{{ item.version || '—' }}</dd>
          <template v-if="item.latest_version">
            <dt>{{ t('harness.latestVersion') }}</dt><dd>{{ item.latest_version }}</dd>
          </template>
          <dt>{{ t('harness.source') }}</dt><dd>{{ t(`harness.source.${item.source}`) }}</dd>
          <dt>{{ t('harness.package') }}</dt><dd>{{ item.package }}</dd>
          <dt>{{ t('harness.node') }}</dt><dd>{{ item.name }}</dd>
        </dl>
        <p v-if="item.executable_path" class="harness-path">{{ item.executable_path }}</p>
        <p v-if="item.error" role="alert" class="harness-error">{{ item.error }}</p>
        <p v-if="item.update_status === 'available'" class="harness-update" role="status">{{ t('harness.updateAvailable') }}</p>
        <p v-else-if="item.update_status === 'current'" class="harness-note">{{ t('harness.upToDate') }}</p>
        <p v-else-if="item.update_status === 'error'" role="alert" class="harness-error">{{ t('harness.updateCheckFailed') }} {{ item.update_error }}</p>
        <p v-if="item.update_status === 'available' && item.upgrade_error" role="alert" class="harness-error">{{ item.upgrade_error }}</p>
        <p v-if="jobs[item.id]?.status === 'failed'" role="alert" class="harness-error">{{ jobs[item.id]?.error }}</p>
        <p v-if="jobs[item.id]?.status === 'completed'" role="status">{{ t('harness.completed') }}</p>
        <div class="harness-actions">
          <ActionButton compact :disabled="busy(item.id)" @click="act(item.id, 'check')">{{ t('harness.check') }}</ActionButton>
          <ActionButton v-if="item.update_status === 'available' && item.status === 'ready'" compact variant="primary" :disabled="busy(item.id) || !item.can_upgrade" @click="act(item.id, 'upgrade')">{{ t('harness.upgrade') }}</ActionButton>
          <ActionButton v-else-if="item.source !== 'external'" compact :variant="item.source === 'managed' ? 'default' : 'primary'" :disabled="busy(item.id)" @click="act(item.id, 'install')">{{ item.source === 'managed' ? t('harness.reinstall') : t('harness.install') }}</ActionButton>
          <ActionButton compact :disabled="busy(item.id) || !item.can_uninstall" @click="act(item.id, 'uninstall')">{{ t('harness.uninstall') }}</ActionButton>
        </div>
        <details v-if="jobs[item.id]?.output"><summary>{{ t('harness.output') }}</summary><pre>{{ jobs[item.id]?.output }}</pre></details>
      </article>
    </div>
  </section>
</template>

<style scoped>
.harness-settings { display: grid; align-content: start; gap: 16px; padding: 20px; overflow: auto; min-height: 0; }
.harness-toolbar,.harness-title,.harness-actions { display: flex; align-items: center; gap: 12px; justify-content: space-between; }
.harness-toolbar p { margin: 0; }
.harness-note { opacity: .7; margin: 0; }
.harness-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(300px,1fr)); gap: 16px; }
.harness-card { border: 1px solid var(--border-color, #8885); border-radius: 12px; padding: 20px; min-width: 0; }
.harness-title a { color: inherit; font-size: 18px; font-weight: 600; }
.harness-status { font-size: 12px; border-radius: 20px; padding: 4px 10px; background: #8882; }
.harness-status.ready { color: #299769; background: #29976918; }
.harness-update { color: #299769; }
.harness-error,.harness-status.error { color: #dc6565; white-space: pre-wrap; overflow-wrap: anywhere; }
dl { display: grid; grid-template-columns: auto 1fr; gap: 8px 16px; font-size: 13px; }
dt { opacity: .65; } dd { margin: 0; overflow-wrap: anywhere; }
.harness-path { font-size: 12px; opacity: .65; overflow-wrap: anywhere; }
.harness-actions { justify-content: flex-start; flex-wrap: wrap; margin-top: 20px; }
details { margin-top: 12px; } pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
</style>
