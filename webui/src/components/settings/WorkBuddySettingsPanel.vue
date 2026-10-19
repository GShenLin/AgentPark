<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { workBuddyAccount, workBuddyService, type WorkBuddyService, type WorkBuddyModel, type WorkBuddyAccount } from '../../workbuddyApi'
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import FormCheckbox from '../FormCheckbox.vue'
import FormTextInput from '../FormTextInput.vue'

const props = defineProps<{ providerId: string }>()
const emit = defineEmits<{ models: [ids: string[]]; connection: [baseUrl: string] }>()
const service = ref<WorkBuddyService | null>(null)
const account = ref<WorkBuddyAccount | null>(null)
const models = ref<WorkBuddyModel[]>([])
const error = ref('')
const busy = ref(false)
const authorizationUrl = ref('')
const loginId = ref('')
let loginExpiresAt = 0
const search = ref('')
const freeOnly = ref(false)
const port = ref('18788')
let revision = 0
let timer: ReturnType<typeof setTimeout> | undefined
const labels = { stopped: '已停止', installing: '正在安装依赖', starting: '正在启动', running: '运行中', stopping: '正在停止', failed: '发生错误' }
const changing = computed(() => ['installing', 'starting', 'stopping'].includes(service.value?.state || ''))
const visibleModels = computed(() => models.value.filter(model => (
  (!freeOnly.value || model.billing.free) && `${model.id} ${model.name}`.toLowerCase().includes(search.value.toLowerCase())
)))

function schedule() {
  clearTimeout(timer)
  timer = setTimeout(() => void refresh(), 2000)
}
async function refresh() {
  const current = revision
  try {
    const next = await workBuddyService()
    if (current !== revision) return
    service.value = next
    if (loginId.value && Date.now() >= loginExpiresAt) {
      loginId.value = ''; authorizationUrl.value = ''
      error.value = '授权链接已过期，请重新登录。'
    }
    if (loginId.value) {
      const result = await workBuddyAccount<{ connected: boolean }>(props.providerId, 'finish', loginId.value)
      if (current !== revision) return
      if (result.connected) {
        loginId.value = ''; authorizationUrl.value = ''
        await loadAccount(current)
      }
    }
  } catch (cause) {
    if (current !== revision) return
    error.value = String((cause as Error).message || cause)
  }
  if (current === revision) schedule()
}
async function loadAccount(current = revision) {
  const id = props.providerId
  const next = await workBuddyAccount<WorkBuddyAccount>(id, 'status')
  const catalog = next.connected ? await workBuddyAccount<{ data: WorkBuddyModel[] }>(id, 'models') : { data: [] }
  if (current !== revision) return
  account.value = next
  models.value = catalog.data
}
async function run(action: () => Promise<void>) {
  busy.value = true; error.value = ''
  try { await action() }
  catch (cause) { error.value = String((cause as Error).message || cause) }
  finally { busy.value = false }
}
async function operate(operation: string) {
  await run(async () => { service.value = await workBuddyService(operation) })
}
async function configure(autoStart: boolean) {
  await run(async () => {
    service.value = await workBuddyService('configure', { autoStart, port: Number(port.value) })
  })
}
async function login() {
  await run(async () => {
    const result = await workBuddyAccount<{ loginId: string; authorizationUrl: string }>(props.providerId, 'login')
    loginId.value = result.loginId; authorizationUrl.value = result.authorizationUrl
    loginExpiresAt = Date.now() + 300000
  })
}
async function logout() {
  await run(async () => {
    await workBuddyAccount(props.providerId, 'logout')
    loginId.value = ''; authorizationUrl.value = ''; models.value = []; account.value = null
  })
}
watch(() => props.providerId, () => {
  revision++; clearTimeout(timer)
  account.value = null; models.value = []; loginId.value = ''; authorizationUrl.value = ''; error.value = ''
  void run(async () => {
    const current = revision
    const next = await workBuddyService()
    if (current !== revision) return
    service.value = next; port.value = String(next.port)
    if (next.state === 'running') await loadAccount(current)
  })
  schedule()
}, { immediate: true })
onBeforeUnmount(() => { revision++; clearTimeout(timer) })
</script>

<template>
  <section class="workbuddy-panel" aria-label="WorkBuddy 服务与账号">
    <div class="heading"><strong>WorkBuddy 服务与账号</strong><span role="status">{{ service ? labels[service.state] : '读取中' }}</span></div>
    <p>AgentPark 管理本机协议服务，无需单独打开终端。先保存 Provider 设置，再连接账号；WorkBuddy 桌面端可照常使用。</p>
    <div class="actions">
      <ActionButton :disabled="busy || changing || service?.state === 'running'" @click="operate('install')">{{ service?.installed ? '重新检查依赖' : '安装服务依赖' }}</ActionButton>
      <ActionButton :disabled="busy || changing || !service?.installed || service?.state === 'running'" @click="operate('start')">启动服务</ActionButton>
      <DangerButton :disabled="busy || changing || service?.state !== 'running'" @click="operate('stop')">停止服务</DangerButton>
      <ActionButton :disabled="busy || !service?.installed" @click="emit('connection', service!.baseUrl)">使用本机服务地址</ActionButton>
    </div>
    <small>停止服务会中断正在使用此服务的节点请求。依赖安装仅在首次使用时需要联网下载。</small>
    <div class="actions">
      <label><FormCheckbox :model-value="service?.autoStart || false" :disabled="busy" @update:model-value="configure($event)" />随 AgentPark 启动</label>
      <label>本机端口 <FormTextInput v-model="port" type="number" :disabled="busy || changing || service?.state === 'running'" /></label>
      <ActionButton :disabled="busy || changing || service?.state === 'running'" @click="configure(service?.autoStart || false)">保存服务设置</ActionButton>
    </div>
    <small v-if="service">日志位置：{{ service.logPath }}</small>
    <p v-if="error || service?.error" class="error" role="alert">{{ error || service?.error }}</p>
    <div class="actions">
      <strong>{{ account?.connected ? `已连接：${account.account}` : '账号尚未连接' }}</strong>
      <ActionButton :disabled="busy || !!loginId" @click="login">登录 WorkBuddy</ActionButton>
      <ActionButton :disabled="busy" @click="run(() => loadAccount())">刷新账号与模型</ActionButton>
      <DangerButton :disabled="busy || !account?.connected" @click="logout">退出此服务账号</DangerButton>
    </div>
    <p v-if="authorizationUrl"><a :href="authorizationUrl" target="_blank" rel="noopener noreferrer">打开 WorkBuddy 授权页面</a> · 授权后自动检测，链接五分钟内有效。</p>
    <template v-if="models.length">
      <div class="actions">
        <FormTextInput v-model="search" placeholder="搜索模型名称或 ID" />
        <label><FormCheckbox v-model="freeOnly" />仅看明确标为免费的模型</label>
        <ActionButton @click="emit('models', models.map(model => model.id))">加入全部模型</ActionButton>
      </div>
      <small>加入模型后请保存 Provider 设置，再在节点中选择。费用未知的模型不会标为免费。</small>
      <div class="catalog">
        <article v-for="model in visibleModels" :key="model.id">
          <div class="heading"><strong>{{ model.name }}</strong><span>{{ model.billing.free ? '免费' : model.billing.label || '费用未知' }}</span></div>
          <code>{{ model.id }}</code>
          <p>{{ model.description }}</p>
          <small>上下文 {{ model.contextWindow.toLocaleString() }} · 输出 {{ model.maxTokens.toLocaleString() }} · {{ model.supportsImages ? '支持图片' : '文本' }}</small>
          <small>思考强度：{{ model.reasoningEfforts.join(' / ') || '未声明' }}</small>
          <small v-if="model.billing.promotionText">{{ model.billing.promotionText }} {{ model.billing.promotionEndsAt }}</small>
          <ActionButton compact @click="emit('models', [model.id])">加入模型</ActionButton>
        </article>
      </div>
    </template>
  </section>
</template>

<style scoped>
.workbuddy-panel { grid-column: 1 / -1; display: grid; gap: 12px; padding: 16px; border: 1px solid var(--border-color, #526079); border-radius: 10px; }
.heading, .actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.heading { justify-content: space-between; }
p { margin: 0; font-size: 13px; line-height: 1.6; }
small { font-size: 12px; opacity: .8; overflow-wrap: anywhere; }
label { display: flex; align-items: center; gap: 8px; }
label input { max-width: 100px; }
.error { color: #f87171; }
a { color: #60a5fa; }
.catalog { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; max-height: 440px; overflow: auto; }
article { display: grid; gap: 7px; padding: 12px; border: 1px solid #64748b66; border-radius: 8px; }
code { overflow-wrap: anywhere; font-size: 11px; }
</style>
