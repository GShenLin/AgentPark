<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ActionButton from '../ActionButton.vue'
import FormTextInput from '../FormTextInput.vue'
import { emptyLocalService, localModelRequest, type LocalService, type LocalServiceConfig,
  type LocalStatus, type LocalJob, type LocalOperation } from '../../localModelApi'

const emit = defineEmits<{ dirty: [value: boolean] }>()
const services = ref<LocalService[]>([])
const selected = ref('')
const status = ref<LocalStatus | null>(null)
const jobs = ref<LocalJob[]>([])
const busy = ref(false)
const scanning = ref(false)
const error = ref('')
const message = ref('')
const editor = ref(false)
const editingId = ref('')
const draft = ref<LocalServiceConfig>(emptyLocalService())
const baseline = ref('')
const extraArgs = ref('')
watch(extraArgs, value => {
  draft.value.extra_args = value.split(/\r?\n/).filter(line => line.length > 0)
}, { flush: 'sync' })
const modelId = ref('')
const query = ref('')
const importing = ref(false)
const source = ref('')
const category = ref('diffusion_models')
let disposed = false
let revision = 0
let timer: ReturnType<typeof setTimeout> | undefined
const current = computed(() => services.value.find(s => s.id === selected.value))
const currentJob = computed(() => jobs.value.filter(j => j.service_id === selected.value).slice(-1)[0])
const running = computed(() => currentJob.value?.state === 'running')
const locked = computed(() => busy.value || scanning.value || running.value)
const dirty = computed(() => editor.value && JSON.stringify(draft.value) !== baseline.value)
watch(dirty, value => emit('dirty', value))
const models = computed(() => (status.value?.models || []).filter(m =>
  `${m.name} ${m.category} ${m.path}`.toLowerCase().includes(query.value.toLowerCase())))
const bytes = (value: number | null) => value === null ? '—' : `${(value / 1024 ** 3).toFixed(2)} GiB`
const modelState = computed(() => !status.value?.online ? '服务离线' : status.value.loaded === true
  ? '模型已加载' : status.value.loaded === false ? '模型未加载' : '逐模型驻留状态不可查询')
const readiness = computed(() => status.value?.online === null ? '未配置就绪检测'
  : status.value?.online ? '就绪检测通过' : '就绪检测未通过')
const supports = (action: LocalOperation['action']) => status.value?.actions.includes(action) === true
const fail = (e: unknown) => { error.value = e instanceof Error ? e.message : String(e) }
const discard = () => !dirty.value || window.confirm('放弃尚未保存的本地服务配置？')

function edit(service?: LocalService) {
  if (!discard()) return
  editingId.value = service?.id || ''
  if (service) {
    const { id: _id, ...config } = service
    draft.value = { ...config, extra_args: [...config.extra_args] }
  } else draft.value = emptyLocalService()
  extraArgs.value = draft.value.extra_args.join('\n')
  baseline.value = JSON.stringify(draft.value)
  editor.value = true
}
function changeKind() {
  const kind = draft.value.kind
  if (!draft.value.name && kind) draft.value.name = kind === 'strata' ? 'Strata' : 'ComfyUI'
  draft.value.endpoint = kind ? `http://127.0.0.1:${kind === 'strata' ? 8080 : 8188}` : ''
  draft.value.python_path = ''; draft.value.workflow_path = ''
  draft.value.executable = ''; draft.value.health_path = ''; draft.value.extra_args = []
  extraArgs.value = ''
}
async function scan() {
  if (!selected.value) return
  const ticket = ++revision
  scanning.value = true; error.value = ''
  try {
    const next = await localModelRequest<LocalStatus>(`/${selected.value}/status`)
    if (disposed || ticket !== revision) return
    status.value = next
    if (!next.models.some(m => m.id === modelId.value)) {
      modelId.value = next.models.find(m => m.available && m.name === next.active_model)?.id
        || next.models.find(m => m.available)?.id || ''
    }
  } catch (e) { if (ticket === revision) fail(e) }
  finally { if (ticket === revision) scanning.value = false }
}
async function select(id: string) {
  if (!discard()) return
  editor.value = false; selected.value = id; status.value = null; modelId.value = ''
  importing.value = false; query.value = ''; message.value = ''; source.value = ''
  await scan()
}
async function refresh() {
  const result = await localModelRequest<{ services: LocalService[]; jobs: LocalJob[] }>()
  if (disposed) return
  services.value = result.services; jobs.value = result.jobs
  if (!services.value.some(s => s.id === selected.value)) selected.value = services.value[0]?.id || ''
}
async function save() {
  busy.value = true; error.value = ''
  try {
    const service = await localModelRequest<LocalService>(editingId.value ? `/${editingId.value}` : '',
      editingId.value ? 'PUT' : 'POST', draft.value)
    editor.value = false; selected.value = service.id; status.value = null
    await refresh(); await scan()
    message.value = '配置已保存'
  } catch (e) { fail(e) } finally { busy.value = false }
}
async function remove() {
  if (!current.value || !window.confirm(`移除 ${current.value.name} 的登记？安装目录和模型文件会保留。`)) return
  busy.value = true; error.value = ''
  try {
    await localModelRequest(`/${selected.value}`, 'DELETE')
    status.value = null; await refresh(); await scan()
  } catch (e) { fail(e) } finally { busy.value = false }
}
async function operate(action: LocalOperation['action']) {
  if (!current.value) return
  busy.value = true; error.value = ''; message.value = ''
  try {
    const job = await localModelRequest<LocalJob>(`/${selected.value}/operations`, 'POST', {
      action, model_id: modelId.value, source_path: source.value, category: category.value,
    })
    jobs.value.push(job)
    importing.value = false
    schedulePoll()
  } catch (e) { fail(e) } finally { busy.value = false }
}
function schedulePoll() {
  if (timer) clearTimeout(timer)
  if (!disposed && jobs.value.some(j => j.state === 'running')) timer = setTimeout(poll, 1200)
}
async function poll() {
  let changed = false
  try {
    for (const job of jobs.value.filter(j => j.state === 'running')) {
      const next = await localModelRequest<LocalJob>(`/jobs/${job.id}`)
      if (disposed) return
      jobs.value = jobs.value.map(j => j.id === next.id ? next : j)
      if (next.service_id === selected.value && next.state !== 'running') changed = true
    }
    if (changed) await scan()
    schedulePoll()
  } catch (e) { fail(e) }
}
async function reconnect() {
  busy.value = true; error.value = ''
  try { await refresh(); await scan(); schedulePoll() }
  catch (e) { fail(e) } finally { busy.value = false }
}
onMounted(reconnect)
onBeforeUnmount(() => { disposed = true; revision++; if (timer) clearTimeout(timer); emit('dirty', false) })
</script>

<template>
  <section class="local-model-panel">
    <div class="local-intro">
      <div><h3>本地服务 <span>LocalModel</span></h3><p>登记任意本地服务，自定义启动方式；可选预设提供模型管理能力。</p></div>
      <div class="local-actions"><ActionButton :disabled="busy" @click="reconnect">刷新</ActionButton>
        <ActionButton :disabled="busy" @click="edit()">添加服务</ActionButton></div>
    </div>
    <p class="local-note">路径指 AgentPark 后端所在电脑。服务由你手动启动和停止；就绪检测只访问配置的检测接口。</p>
    <div v-if="error" class="local-error" role="alert">{{ error }}</div>
    <p v-if="message" role="status">{{ message }}</p>
    <div class="local-layout">
      <nav class="local-services" aria-label="本地服务">
        <button v-for="service in services" :key="service.id" :class="{ active: selected === service.id }"
          :disabled="busy" @click="select(service.id)">
          <strong>{{ service.name }}</strong><small>{{ service.kind === 'strata' ? 'Strata 预设' : service.kind === 'comfyui' ? 'ComfyUI 预设' : '自定义服务' }}</small>
        </button>
        <p v-if="!services.length">尚未登记服务。可添加启动程序，也可仅登记已有服务地址。</p>
      </nav>
      <div class="local-content">
        <form v-if="editor" class="local-card local-form" @submit.prevent="save">
          <h4>{{ editingId ? '编辑服务' : '添加本地服务' }}</h4>
          <label>名称<FormTextInput v-model="draft.name" :disabled="busy" required /></label>
          <details :open="draft.kind !== null" class="local-preset">
            <summary>使用管理预设（可选）</summary>
            <p class="local-note">预设提供启动方式及模型操作。切换会重置服务地址、启动参数和专用设置。</p>
            <label>管理预设<select v-model="draft.kind" :disabled="busy" @change="changeKind"><option :value="null">不使用预设</option><option value="strata">Strata</option><option value="comfyui">ComfyUI</option></select></label>
          </details>
          <label>{{ draft.kind ? '安装目录' : '工作目录（配置启动程序时必填）' }}<FormTextInput v-model="draft.install_path" :disabled="busy" placeholder="例如 C:\Services\MyService" :required="!!draft.kind || !!draft.executable" /></label>
          <p v-if="draft.kind" class="local-note">Strata 选择包含 serve/server.py 的目录；ComfyUI 选择包含 main.py 的目录。</p>
          <label v-if="!draft.kind">启动程序（可选）<FormTextInput v-model="draft.executable" :disabled="busy" placeholder="可执行文件的绝对路径，例如 C:\Python\python.exe" /></label>
          <p v-if="!draft.kind" class="local-note">可直接启动任意可执行程序。脚本请将解释器填在上方，将脚本路径填入参数；进程应保持前台运行，停止时会结束其进程树。</p>
          <label v-if="draft.kind">Python 可执行文件（可选）<FormTextInput v-model="draft.python_path" :disabled="busy" placeholder="留空使用安装目录内的 .venv" /></label>
          <label>{{ draft.kind ? '附加启动参数（可选，一行一个参数）' : '启动参数（可选，一行一个参数，路径无需加引号）' }}<textarea v-model="extraArgs" :disabled="busy" rows="4" :placeholder="draft.kind ? '例如 --lowvram' : '例如：\nC:\\Services\\MyService\\server.py\n--port\n9000'" /></label>
          <label>{{ draft.kind ? '服务地址' : '服务地址（可选，仅登记服务时必填）' }}<FormTextInput v-model="draft.endpoint" :disabled="busy" placeholder="例如 http://127.0.0.1:9000" :required="!!draft.kind || !draft.executable" /></label>
          <p v-if="!draft.kind" class="local-note">服务地址用于打开服务和检测端口占用；实际监听地址由程序及启动参数决定。</p>
          <label v-if="!draft.kind">就绪检测路径（可选）<FormTextInput v-model="draft.health_path" :disabled="busy" placeholder="例如 /health；HTTP 2xx 表示检测通过" /></label>
          <p v-if="!draft.kind" class="local-note">留空只记录进程状态，不判断服务是否就绪。检测路径应是可安全重复访问的 GET 接口。</p>
          <label v-if="draft.kind || draft.health_path">启动等待时间（秒）<input v-model.number="draft.startup_timeout" type="number" min="1" max="600" :disabled="busy" required /></label>
          <label v-if="draft.kind === 'comfyui'">API 工作流文件（可选）<FormTextInput v-model="draft.workflow_path" :disabled="busy" placeholder="已导出为 API 格式的工作流 JSON 绝对路径" /></label>
          <div class="local-actions"><ActionButton :disabled="busy" @click="save">保存并检测</ActionButton>
            <ActionButton :disabled="busy" @click="() => { if (discard()) editor = false }">取消</ActionButton></div>
        </form>
        <template v-else-if="current">
          <div class="local-card">
            <div class="local-intro"><h4>{{ current.name }}</h4><div class="local-actions">
              <ActionButton :disabled="locked || status?.managed" @click="edit(current)">编辑</ActionButton>
              <ActionButton :disabled="locked || status?.managed" @click="remove">移除登记</ActionButton></div></div>
            <p class="local-path">{{ current.install_path }}</p>
            <p v-if="current.executable" class="local-path">{{ current.executable }}</p>
            <a v-if="current.endpoint" :href="current.endpoint" target="_blank" rel="noopener noreferrer">{{ current.endpoint }} ↗</a>
            <p v-if="scanning" role="status">正在检测服务状态…</p>
            <template v-if="status">
              <div class="local-badges"><span :class="{ good: status.launchable }">{{ status.launchable ? '启动配置可用' : '启动配置待完善' }}</span>
                <span :class="{ good: status.managed }">{{ status.managed ? '本模块启动的进程运行中' : status.exit_code !== null ? `进程已退出（${status.exit_code}）` : '本模块未启动进程' }}</span>
                <span :class="{ good: status.online }">{{ readiness }}</span><span v-if="supports('load')">{{ modelState }}</span></div>
              <p v-if="status.active_model">当前模型：{{ status.active_model }}</p>
              <p v-for="issue in status.launch_issues" :key="issue" class="local-note">{{ issue }}</p>
              <p v-if="current.kind && !status.installed" class="local-note">未找到预设要求的安装入口，请检查安装目录。</p>
              <p v-if="current.kind === 'comfyui'" class="local-note">ComfyUI 按工作流加载模型。“执行工作流”会实际生成结果；模型文件列表不代表已驻留显存。</p>
              <p v-if="status.online && !status.managed" class="local-note">检测接口可访问，但进程不由本次 AgentPark 管理；停止服务请使用原入口。</p>
              <details v-if="status.connection_error"><summary>连接检测详情</summary><pre>{{ status.connection_error }}</pre></details>
              <p v-for="issue in status.issues" :key="issue" class="local-error">{{ issue }}</p>
              <label v-if="current.kind === 'strata'">运行配置<select v-model="modelId" :disabled="locked">
                <option value="">请选择</option><option v-for="model in status.models" :key="model.id" :value="model.id" :disabled="!model.available">{{ model.name }} · {{ model.id }}</option>
              </select></label>
              <div class="local-actions local-operation-actions">
                <ActionButton :disabled="locked" @click="scan">检测状态</ActionButton>
                <ActionButton :disabled="locked || status.online === true || status.managed || !status.launchable || (current.kind === 'strata' && !modelId)" @click="operate('start')">启动服务</ActionButton>
                <ActionButton :disabled="locked || !status.managed" @click="operate('stop')">停止服务</ActionButton>
                <ActionButton v-if="supports('load')" :disabled="locked || !status.online || (current.kind === 'strata' ? !modelId : !current.workflow_path)" @click="operate('load')">{{ current.kind === 'strata' ? '加载模型' : '执行工作流' }}</ActionButton>
                <ActionButton v-if="supports('unload')" :disabled="locked || !status.online" @click="operate('unload')">{{ current.kind === 'strata' ? '卸载模型' : '释放模型' }}</ActionButton>
              </div>
            </template>
          </div>
          <div v-if="currentJob" class="local-card local-job" :class="{ 'local-error': currentJob.state === 'failed' }" role="status">
            <strong>{{ currentJob.state === 'running' ? '操作进行中' : currentJob.state === 'failed' ? '操作失败' : '操作结果' }}</strong><p>{{ currentJob.message }}</p>
          </div>
          <div v-if="supports('import')" class="local-card">
            <div class="local-intro"><h4>已发现模型 <span>{{ status?.models.length || 0 }}</span></h4>
              <ActionButton :disabled="locked || !status?.installed" @click="importing = !importing">添加本地模型</ActionButton></div>
            <form v-if="importing" class="local-form local-import" @submit.prevent="operate('import')">
              <p>{{ current.kind === 'strata' ? '登记已有 Strata 运行配置（JSON），保留权重原路径；仅支持 Strata 兼容的模型。' : '将已有模型文件复制到所选模型目录，不覆盖同名文件。' }}</p>
              <label>源文件绝对路径<FormTextInput v-model="source" required /></label>
              <label v-if="current.kind === 'comfyui'">模型类型<select v-model="category">
                <option v-for="name in ['checkpoints', 'diffusion_models', 'unet', 'text_encoders', 'clip', 'vae', 'loras', 'controlnet', 'upscale_models', 'embeddings', 'clip_vision', 'audio_encoders']" :key="name">{{ name }}</option>
              </select></label>
              <ActionButton :disabled="locked || !source.trim()" @click="operate('import')">{{ current.kind === 'strata' ? '登记配置' : '复制并添加' }}</ActionButton>
            </form>
            <FormTextInput v-model="query" type="search" placeholder="搜索模型、类型或路径" aria-label="搜索模型" />
            <div class="local-model-list"><article v-for="model in models" :key="model.id + model.category" class="local-model-row">
              <div><strong>{{ model.name }}</strong><small>{{ model.category }} · {{ bytes(model.bytes) }} · {{ model.available ? '文件存在' : '缺少文件' }}</small>
                <p class="local-path">{{ model.path }}</p><p v-if="model.missing.length" class="local-error">{{ model.missing.join('；') }}</p></div>
            </article></div>
            <p v-if="!models.length && !scanning" class="local-note">{{ query ? '没有匹配的模型。' : '没有发现模型。请检查安装路径、模型目录或添加本地模型。' }}</p>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped src="./LocalModelSettingsPanel.css"></style>
