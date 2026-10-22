<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getActiveApiBase } from './api'
import type { UserInteractionRequest } from './apiTypes'
import { getUserInteraction, submitUserInteraction } from './userInteractionApi'
import { subscribeAppEvents } from './composables/useAppEventStream'
import { clearInteractionDraft } from './interactionFormState'
import UserInteractionForm from './components/UserInteractionForm.vue'
import ActionButton from './components/ActionButton.vue'

const bridge = window.agentParkNodeWindow
if (!bridge?.target.requestId) throw new Error('Interaction window host is required')
const host = bridge, requestId = bridge.target.requestId
const request = ref<UserInteractionRequest | null>(null)
const error = ref(''), submitting = ref(false)
let refreshing: Promise<void> | null = null
let refreshQueued = false, disposed = false
const statusLabel = computed(() => {
  if (!request.value) return '正在加载请求'
  return { pending: '等待你的输入', submitted: '已提交，Agent 将继续执行', cancelled: '请求已取消', expired: '请求已过期' }[request.value.status]
})

async function refresh() {
  if (refreshing) { refreshQueued = true; return refreshing }
  refreshing = (async () => {
    do {
      refreshQueued = false
      const result = await getUserInteraction(requestId)
      if (disposed) return
      if (request.value && request.value.status !== 'pending' && result.status === 'pending') continue
      request.value = result
      document.title = `${result.schema.title} · AgentPark`
      if (result.status !== 'pending') clearInteractionDraft(requestId, getActiveApiBase(), localStorage)
    } while (refreshQueued && !disposed)
  })()
  try { await refreshing }
  finally { refreshing = null }
}

async function refreshVisible() {
  try { await refresh(); error.value = '' }
  catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
}

const stopEvents = subscribeAppEvents(event => {
  if (event.event === 'stream_gap' || event.event === 'stream_snapshot'
    || (event.event === 'runtime_notice' && event.source === 'user_interaction')
    || (typeof event.event === 'string' && event.event.startsWith('user_interaction_'))) void refreshVisible()
})

async function submit(response: Record<string, unknown>, id: string, status: 'submitted' | 'cancelled' = 'submitted') {
  if (submitting.value || id !== requestId || request.value?.status !== 'pending') return
  submitting.value = true
  error.value = ''
  try {
    const result = await submitUserInteraction(requestId, response, status)
    request.value = result.request
    clearInteractionDraft(requestId, getActiveApiBase(), localStorage)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    // Re-read the authority after a competing submission or an uncertain network result.
    try { await refresh() }
    catch (refreshError) { error.value += `；状态刷新失败：${String(refreshError)}` }
  } finally { submitting.value = false }
}

onMounted(async () => {
  document.documentElement.classList.add('interaction-window-document')
  try {
    await host.setMode('card', 500, 650)
    await refresh()
    host.ready()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    host.fail(error.value)
  }
})

onBeforeUnmount(() => {
  disposed = true
  stopEvents()
  document.documentElement.classList.remove('interaction-window-document')
})
</script>

<template>
  <main class="interaction-widget">
    <header class="interaction-widget-header">
      <div class="interaction-widget-heading">
        <span class="interaction-widget-status">{{ statusLabel }}</span>
        <h1>{{ request?.schema.title || 'AgentPark 交互' }}</h1>
      </div>
      <ActionButton compact title="最小化到任务栏，稍后填写" @click="host.minimize">稍后</ActionButton>
      <ActionButton v-if="request && request.status !== 'pending'" compact @click="host.close">关闭</ActionButton>
    </header>
    <div v-if="request?.status === 'pending'" class="interaction-widget-meta">
      <span>填写后提交给 Agent</span>
    </div>
    <section class="interaction-widget-content">
      <UserInteractionForm v-if="request?.status === 'pending'" :request="request" :submitting="submitting" :error="error"
        @submit="submit" @cancel="submit({ error: '用户取消了交互请求' }, $event, 'cancelled')" @error="error = $event" />
      <template v-else>
        <p>{{ statusLabel }}</p>
        <p v-if="request?.response?.error">{{ request.response.error }}</p>
        <p v-if="error" class="interaction-widget-error" role="alert">{{ error }}</p>
        <ActionButton v-if="!request" @click="refreshVisible().then(() => { if (request) host.ready() })">重试加载</ActionButton>
      </template>
    </section>
  </main>
</template>

<style>
html.interaction-window-document, .interaction-window-document body, .interaction-window-document #app {
  background: transparent !important; min-width: 0; overflow: hidden;
}
.interaction-widget { height: calc(100dvh - 16px); margin: 8px; display: flex; flex-direction: column; border: 1px solid var(--ui-dialog-border); border-radius: 14px; background: var(--ui-dialog-background); color: var(--ui-dialog-text); overflow: hidden; box-shadow: 0 5px 18px #0003; }
.interaction-widget-header { display: flex; align-items: center; gap: 8px; padding: 18px; border-bottom: 1px solid var(--ui-dialog-border); -webkit-app-region: drag; }
.interaction-widget-header button { -webkit-app-region: no-drag; }
.interaction-widget-heading { min-width: 0; flex: 1; }
.interaction-widget-heading h1 { font-size: 18px; margin: 6px 0 0; line-height: 1.4; overflow-wrap: anywhere; }
.interaction-widget-status { font-size: 12px; color: var(--ui-primary-text, #93c5fd); }
.interaction-widget-meta { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px; padding: 12px 18px 0; font-size: 12px; color: var(--text-secondary); }
.interaction-widget-content { flex: 1; min-height: 0; overflow: auto; padding: 18px; }
.interaction-widget-error { color: var(--text-danger, #ef7070); }
.interaction-widget-content .interaction-actions { position: sticky; bottom: -18px; background: var(--ui-dialog-background); padding-bottom: 12px; }
</style>
