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
const extraArgs = computed({ get: () => draft.value.extra_args.join('\n'),
  set: (value: string) => { draft.value.extra_args = value.split('\n').map(x => x.trim()).filter(Boolean) } })
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
const fail = (e: unknown) => { error.value = e instanceof Error ? e.message : String(e) }
const discard = () => !dirty.value || window.confirm('放弃尚未保存的本地服务配置？')

function edit(service?: LocalService) {
  if (!discard()) return
  editingId.value = service?.id || ''
  if (service) {
    const { id: _id, ...config } = service
    draft.value = { ...config }
  } else draft.value = emptyLocalService()
  baseline.value = JSON.stringify(draft.value)
  editor.value = true
}
function changeKind() {
  draft.value.name = draft.value.kind === 'strata' ? 'Strata' : 'ComfyUI'
  draft.value.endpoint = `http://127.0.0.1:${draft.value.kind === 'strata' ? 8080 : 8188}`
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
      <div><h3>本地模型 <span>LocalModel</span></h3><p>配置本机推理服务，手动启动、加载和释放模型。</p></div>
      <div class="local-actions"><ActionButton :disabled="busy" @click="reconnect">刷新</ActionButton>
        <ActionButton :disabled="busy" @click="edit()">添加服务</ActionButton></div>
    </div>
    <p class="local-note">路径指 AgentPark 后端所在电脑。检测不会加载模型；本模块不自动启动、卸载或调度服务。</p>
    <div v-if="error" class="local-error" role="alert">{{ error }}</div>
    <p v-if="message" role="status">{{ message }}</p>
    <div class="local-layout">
      <nav class="local-services" aria-label="本地服务">
        <button v-for="service in services" :key="service.id" :class="{ active: selected === service.id }"
          :disabled="busy" @click="select(service.id)">
          <strong>{{ service.name }}</strong><small>{{ service.kind === 'strata' ? 'Strata' : 'ComfyUI' }}</small>
        </button>
        <p v-if="!services.length">尚未登记服务。添加安装路径后即可检测已有模型。</p>
      </nav>
      <div class="local-content">
        <form v-if="editor" class="local-card local-form" @submit.prevent="save">
          <h4>{{ editingId ? '编辑服务' : '添加本地服务' }}</h4>
          <label>服务类型<select v-model="draft.kind" :disabled="busy" @change="changeKind"><option value="strata">Strata</option><option value="comfyui">ComfyUI</option></select></label>
          <label>名称<FormTextInput v-model="draft.name" :disabled="busy" required /></label>
          <label>安装目录<FormTextInput v-model="draft.install_path" :disabled="busy" placeholder="例如 C:\Project\Strata" required /></label>
          <p class="local-note">Strata 选择包含 serve/server.py 的目录；ComfyUI 选择包含 main.py 的目录。</p>
          <label>服务地址<FormTextInput v-model="draft.endpoint" :disabled="busy" required /></label>
          <label>Python 可执行文件（可选）<FormTextInput v-model="draft.python_path" :disabled="busy" placeholder="留空使用安装目录内的 .venv" /></label>
          <label>附加启动参数（可选，一行一个参数）<textarea v-model="extraArgs" :disabled="busy" rows="3" placeholder="例如 --lowvram" /></label>
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
            <a :href="current.endpoint" target="_blank" rel="noopener noreferrer">{{ current.endpoint }} ↗</a>
            <p v-if="scanning" role="status">正在检测安装、模型与服务状态…</p>
            <template v-if="status">
              <div class="local-badges"><span :class="{ good: status.installed }">{{ status.installed ? '安装入口存在' : '安装入口缺失' }}</span>
                <span :class="{ good: status.online }">{{ status.online ? '服务在线' : '服务离线' }}</span><span>{{ modelState }}</span></div>
              <p v-if="status.active_model">当前模型：{{ status.active_model }}</p>
              <p v-if="!status.python_exists" class="local-note">未找到 Python 环境，请编辑服务配置。已运行的服务仍可通过接口管理。</p>
              <p v-if="current.kind === 'comfyui'" class="local-note">ComfyUI 按工作流加载模型。“执行工作流”会实际生成结果；模型文件列表不代表已驻留显存。</p>
              <p v-if="status.online && !status.managed" class="local-note">服务由外部入口启动，或早于本次 AgentPark 启动。可加载／释放模型；停止服务请使用原入口。</p>
              <details v-if="status.connection_error"><summary>连接检测详情</summary><pre>{{ status.connection_error }}</pre></details>
              <p v-for="issue in status.issues" :key="issue" class="local-error">{{ issue }}</p>
              <label v-if="current.kind === 'strata'">运行配置<select v-model="modelId" :disabled="locked">
                <option value="">请选择</option><option v-for="model in status.models" :key="model.id" :value="model.id" :disabled="!model.available">{{ model.name }} · {{ model.id }}</option>
              </select></label>
              <div class="local-actions local-operation-actions">
                <ActionButton :disabled="locked" @click="scan">检测模型</ActionButton>
                <ActionButton :disabled="locked || status.online || status.managed || !status.installed || !status.python_exists || (current.kind === 'strata' && !modelId)" @click="operate('start')">启动服务</ActionButton>
                <ActionButton :disabled="locked || !status.managed" @click="operate('stop')">停止服务</ActionButton>
                <ActionButton :disabled="locked || !status.online || (current.kind === 'strata' ? !modelId : !current.workflow_path)" @click="operate('load')">{{ current.kind === 'strata' ? '加载模型' : '执行工作流' }}</ActionButton>
                <ActionButton :disabled="locked || !status.online" @click="operate('unload')">{{ current.kind === 'strata' ? '卸载模型' : '释放模型' }}</ActionButton>
              </div>
            </template>
          </div>
          <div v-if="currentJob" class="local-card local-job" :class="{ 'local-error': currentJob.state === 'failed' }" role="status">
            <strong>{{ currentJob.state === 'running' ? '操作进行中' : currentJob.state === 'failed' ? '操作失败' : '操作结果' }}</strong><p>{{ currentJob.message }}</p>
          </div>
          <div class="local-card">
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
