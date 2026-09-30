<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ActionButton from '../ActionButton.vue'
import FormTextInput from '../FormTextInput.vue'
import { nodeSyncClient, type SyncCloudStatus } from '../../nodeSyncApi'

const props = defineProps<{ api: ReturnType<typeof nodeSyncClient>; disabled: boolean }>()
const emit = defineEmits<{ refresh: [] }>()
const status = ref<SyncCloudStatus | null>(null)
const password = ref('')
const busy = ref(false)
const expanded = ref(false)
const error = ref('')
async function run(action: 'login' | 'logout' | 'status') {
  busy.value = true; error.value = ''
  try {
    status.value = action === 'login' ? await props.api.cloudLogin(password.value)
      : action === 'logout' ? await props.api.cloudLogout() : await props.api.cloudStatus()
    if (action !== 'status') { expanded.value = false; emit('refresh') }
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { password.value = ''; busy.value = false }
}
onMounted(() => { void run('status') })
</script>

<template>
  <section class="sync-cloud">
    <div class="sync-cloud-row">
      <strong>远程设备</strong>
      <span v-if="status">{{ status.connected ? '已连接设备中心' : '尚未连接设备中心' }} · {{ status.origin }}</span>
      <ActionButton compact :disabled="disabled || busy" @click="expanded = !expanded">{{ status?.connected ? '重新登录' : '连接远程设备' }}</ActionButton>
      <ActionButton compact :disabled="disabled || busy" @click="emit('refresh')">刷新列表</ActionButton>
      <ActionButton v-if="status?.connected" compact :disabled="disabled || busy" @click="run('logout')">断开</ActionButton>
    </div>
    <form v-if="expanded" class="sync-cloud-login" @submit.prevent="run('login')">
      <p>使用云端设备中心的登录密码，加载同一设备中心的在线设备。服务器地址沿用“设备互联”的设置。</p>
      <label>设备中心密码<FormTextInput v-model="password" type="password" autocomplete="current-password" required :disabled="disabled || busy" aria-label="设备中心密码" /></label>
      <ActionButton type="submit" :disabled="disabled || busy || !password">登录并加载设备</ActionButton>
      <small>密码不保存；登录会话仅保留在当前 AgentPark 服务内存中。服务重启后需要重新登录。</small>
    </form>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.sync-cloud { border: 1px solid var(--ui-control-border); border-radius: 12px; padding: 14px; }
.sync-cloud-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sync-cloud-row span, small { font-size: 13px; opacity: .8; overflow-wrap: anywhere; }
.sync-cloud-login { display: grid; gap: 12px; margin-top: 14px; max-width: 580px; }
.sync-cloud-login label { display: grid; gap: 6px; }
p { margin: 8px 0; } [role=alert] { color: var(--theme-panel-settings-error-text, #dc4545); }
</style>
