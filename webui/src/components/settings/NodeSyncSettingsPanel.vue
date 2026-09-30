<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import ActionButton from '../ActionButton.vue'
import FormSelect from '../FormSelect.vue'
import FormTextInput from '../FormTextInput.vue'
import AccessUsernameDialog from '../AccessUsernameDialog.vue'
import { getAccessUsername, setAccessUsername } from '../../accessIdentity'
import { nodeSyncClient, sameSyncSelection, syncRemoteLabel, needsSyncUsername, type SyncRemote, type SyncJob, type SyncOption, type SyncSelection } from '../../nodeSyncApi'
import SyncCloudConnection from './SyncCloudConnection.vue'

const api = nodeSyncClient()
const remotes = ref<SyncRemote[]>([])
const createSide = (label: string) => ({ label, remote_id: '', graph_id: '', node_id: '',
  graphs: [] as SyncOption[], nodes: [] as SyncOption[], loading: false, revision: 0 })
const sides = reactive([createSide('来源'), createSide('目标')])
const job = ref<SyncJob | null>(null)
const busy = ref(false)
const error = ref('')
const showCreate = ref(false)
const newGraphId = ref('')
const newGraphName = ref('')
const identitySide = ref<number | null>(null)
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined
const running = computed(() => !!job.value && ['preparing', 'applying'].includes(job.value.state))
const disabled = computed(() => busy.value || running.value)
const wholeGraph = computed(() => sides.every(s => !s.node_id))
const selection = (i: number): SyncSelection => ({ remote_id: sides[i]!.remote_id,
  graph_id: sides[i]!.graph_id, node_id: sides[i]!.node_id || null })
const valid = computed(() => sides.every(s => s.remote_id && s.graph_id && !s.loading)
  && sides.every(s => remotes.value.some(r => r.id === s.remote_id && r.available))
  && !!sides[0]!.node_id === !!sides[1]!.node_id
  && !sameSyncSelection(selection(0), selection(1)))
const matching = computed(() => job.value && sameSyncSelection(job.value.selection.source, selection(0))
  && sameSyncSelection(job.value.selection.target, selection(1)))
const canCommit = computed(() => valid.value && matching.value && job.value?.state === 'ready'
  && !job.value.result?.conflicts.length)
const bytes = (n: number) => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(2)} MB`
const fail = (e: unknown) => { error.value = e instanceof Error ? e.message : String(e) }

async function loadGraphs(index: number, reset = true) {
  const side = sides[index]!
  const revision = ++side.revision
  if (reset) { side.graph_id = ''; side.node_id = ''; side.nodes = [] }
  side.graphs = []; side.loading = true; error.value = ''
  if (needsSyncUsername(side.remote_id) && !getAccessUsername()) {
    identitySide.value = index; side.loading = false; return
  }
  try {
    const graphs = await api.graphs(side.remote_id)
    if (!disposed && revision === side.revision) side.graphs = graphs
  } catch (e) { if (revision === side.revision) fail(e) }
  finally { if (revision === side.revision) side.loading = false }
}
async function refreshRemotes() {
  busy.value = true; error.value = ''
  try {
    remotes.value = await api.remotes()
    for (let i = 0; i < sides.length; i++) {
      const side = sides[i]!
      if (!remotes.value.some(r => r.id === side.remote_id && r.available)) {
        side.revision++; side.graphs = []; side.nodes = []
      } else if (!side.graphs.length) {
        await loadGraphs(i, false)
        if (side.graph_id) await loadNodes(i, false)
      }
    }
  } catch (e) { fail(e) } finally { busy.value = false }
}
async function loadNodes(index: number, reset = true) {
  const side = sides[index]!
  const revision = ++side.revision
  if (reset) side.node_id = ''
  side.nodes = []; side.loading = true; error.value = ''
  try {
    const nodes = await api.nodes(side.remote_id, side.graph_id)
    if (!disposed && revision === side.revision) side.nodes = nodes
  } catch (e) { if (revision === side.revision) fail(e) }
  finally { if (revision === side.revision) side.loading = false }
}
async function submitIdentity(username: string) {
  setAccessUsername(username)
  identitySide.value = null
  for (let i = 0; i < sides.length; i++) {
    if (sides[i]!.remote_id && !sides[i]!.graphs.length) {
      await loadGraphs(i, false)
      if (sides[i]!.graph_id) await loadNodes(i, false)
    }
  }
}
async function poll() {
  if (!job.value || disposed) return
  try { job.value = await api.job(job.value.id) } catch (e) { fail(e) }
  finally { if (!disposed && running.value) timer = setTimeout(poll, 1200) }
}
function remember(value: SyncJob) {
  job.value = value
  localStorage.setItem(api.storageKey, value.id)
  if (timer) clearTimeout(timer)
  void poll()
}
async function preview() {
  busy.value = true; error.value = ''
  try { remember(await api.preview(selection(0), selection(1))) }
  catch (e) { fail(e) } finally { busy.value = false }
}
async function start(action: 'preview' | 'commit') {
  if (!job.value) return
  busy.value = true; error.value = ''
  try { remember(await api.resume(job.value.id, action)) }
  catch (e) { fail(e) } finally { busy.value = false }
}
async function createGraph() {
  busy.value = true; error.value = ''
  try {
    await api.createGraph(sides[1]!.remote_id, newGraphId.value.trim(), newGraphName.value.trim() || newGraphId.value.trim())
    await loadGraphs(1)
    sides[1]!.graph_id = newGraphId.value.trim()
    await loadNodes(1)
    showCreate.value = false
  } catch (e) { fail(e) } finally { busy.value = false }
}
onMounted(async () => {
  busy.value = true
  try {
    remotes.value = await api.remotes()
    const previous = localStorage.getItem(api.storageKey)
    if (previous) {
      job.value = await api.job(previous)
      Object.assign(sides[0]!, job.value.selection.source, { node_id: job.value.selection.source.node_id || '' })
      Object.assign(sides[1]!, job.value.selection.target, { node_id: job.value.selection.target.node_id || '' })
      for (let i = 0; i < sides.length; i++) {
        await loadGraphs(i, false)
        if (sides[i]!.graph_id && identitySide.value === null) await loadNodes(i, false)
      }
      void poll()
    } else {
      for (let i = 0; i < sides.length; i++) { sides[i]!.remote_id = 'default'; await loadGraphs(i) }
    }
  } catch (e) { fail(e) } finally { busy.value = false }
})
onBeforeUnmount(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>

<template>
  <section class="node-sync-panel">
    <AccessUsernameDialog v-if="identitySide !== null" @submit="submitIdentity" />
    <p>在两个节点之间增量同步对话；两边都不选节点时，同步整个 Graph 的结构和所有节点的对话。</p>
    <SyncCloudConnection :api="api" :disabled="disabled" @refresh="refreshRemotes" />
    <div class="node-sync-sides">
      <section v-for="(side, index) in sides" :key="side.label" class="node-sync-side">
        <h3>{{ side.label }}{{ index === 0 ? ' →' : '' }}</h3>
        <label>远端
          <FormSelect v-model="side.remote_id" :aria-label="side.label + '远端'" :disabled="disabled || side.loading" @change="loadGraphs(index)">
            <option disabled value="">选择远端</option>
            <option v-if="side.remote_id && !remotes.some(r => r.id === side.remote_id)" :value="side.remote_id" disabled>上次选择的设备未连接 · 请登录或刷新列表</option>
            <option v-for="remote in remotes" :key="remote.id" :value="remote.id" :disabled="!remote.available">{{ syncRemoteLabel(remote) }}</option>
          </FormSelect>
        </label>
        <label>Graph
          <FormSelect v-model="side.graph_id" :aria-label="side.label + 'Graph'" :disabled="disabled || side.loading || !side.remote_id" @change="loadNodes(index)">
            <option disabled value="">选择 Graph</option>
            <option v-for="graph in side.graphs" :key="graph.id" :value="graph.id">{{ graph.name }}</option>
          </FormSelect>
        </label>
        <label>节点
          <FormSelect v-model="side.node_id" :aria-label="side.label + '节点'" :disabled="disabled || side.loading || !side.graph_id">
            <option value="">不选节点 · 整个 Graph</option>
            <option v-for="node in side.nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
          </FormSelect>
        </label>
        <small v-if="side.loading">正在加载…</small>
        <ActionButton v-if="index === 1" compact :disabled="disabled || !side.remote_id" @click="showCreate = !showCreate">新建目标 Graph</ActionButton>
        <form v-if="index === 1 && showCreate" class="node-sync-create" @submit.prevent="createGraph">
          <FormTextInput v-model="newGraphId" required pattern="[A-Za-z0-9_-]+" placeholder="Graph ID（英文、数字、横线）" aria-label="新 Graph ID" :disabled="disabled" />
          <FormTextInput v-model="newGraphName" placeholder="显示名称（可选）" aria-label="新 Graph 名称" :disabled="disabled" />
          <ActionButton type="submit" :disabled="disabled || !newGraphId.trim()">创建并选择</ActionButton>
        </form>
      </section>
    </div>
    <p v-if="!!sides[0]!.node_id !== !!sides[1]!.node_id" role="alert">请两边都选择具体节点，或两边都选择“整个 Graph”。</p>
    <div class="node-sync-notes">
      <p>只同步用户消息、最终回答及其附件，包含 Archive；不传输 Process。保留目标已有对话，不同步删除，不触发 Agent 工作。</p>
      <p v-if="wholeGraph">整图模式按节点 ID 对应，同步配置、位置、连线和分组。已有同名配置以来源为准；保留目标额外节点。工作路径原样复制，模型账号、插件安装、任务队列和组内动态不复制。</p>
      <p>两端需要更新到支持同步的版本。目标有正在执行或排队的任务时会停止提交，空闲后可重试；关闭设置页不影响已开始的后台任务。</p>
    </div>
    <div class="node-sync-actions">
      <ActionButton :disabled="disabled || !valid" @click="preview">预览同步</ActionButton>
      <ActionButton variant="primary" :disabled="disabled || !canCommit" @click="start('commit')">开始同步</ActionButton>
      <ActionButton v-if="job && ['failed', 'interrupted'].includes(job.state)" :disabled="disabled || !matching" @click="start(job.action || 'preview')">继续上次任务</ActionButton>
    </div>
    <p v-if="error" class="node-sync-error" role="alert">{{ error }}</p>
    <section v-if="job" class="node-sync-result" aria-live="polite">
      <h3>{{ job.phase }}</h3>
      <p v-if="job.action === 'commit' && job.result">已提交 {{ job.completed_nodes }} / {{ job.result.nodes }} 个节点。</p>
      <p v-if="!matching">以下结果属于上次选择。当前选择需要重新预览。</p>
      <p v-if="job.error" class="node-sync-error" role="alert">{{ job.error }}</p>
      <template v-if="job.result">
        <dl>
          <div><dt>节点</dt><dd>{{ job.result.nodes }}</dd></div>
          <div><dt>新增消息</dt><dd>{{ job.result.added }}</dd></div>
          <div><dt>更新消息</dt><dd>{{ job.result.updated }}</dd></div>
          <div><dt>无需更新</dt><dd>{{ job.result.unchanged }}</dd></div>
          <div><dt>消息清单</dt><dd>{{ bytes(job.result.message_bytes) }}</dd></div>
          <div><dt>附件</dt><dd>{{ job.result.attachments }} 个 · {{ bytes(job.result.attachment_bytes) }}</dd></div>
          <div><dt>结构配置变更</dt><dd>{{ job.result.structure_files }}</dd></div>
          <div><dt>分组变更</dt><dd>{{ job.result.groups_changed }}</dd></div>
        </dl>
        <details v-if="job.result.structure_changes.length" open><summary>将应用的结构变更</summary><ul><li v-for="item in job.result.structure_changes" :key="item">{{ item }}</li></ul></details>
        <div v-if="job.result.conflicts.length" class="node-sync-error"><strong>存在冲突，尚未提交</strong><ul><li v-for="item in job.result.conflicts" :key="item">{{ item }}</li></ul></div>
        <details v-if="job.result.warnings.length"><summary>同步说明（{{ job.result.warnings.length }}）</summary><ul><li v-for="(item, i) in job.result.warnings" :key="i">{{ item }}</li></ul></details>
      </template>
    </section>
  </section>
</template>

<style scoped>
.node-sync-panel { padding: 20px; overflow: auto; min-height: 0; line-height: 1.65; }
.node-sync-panel p { margin: 0 0 14px; }
.node-sync-sides { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; margin: 20px 0; }
.node-sync-side, .node-sync-result { border: 1px solid var(--ui-control-border); border-radius: 12px; padding: 20px; min-width: 0; }
.node-sync-side h3, .node-sync-result h3 { margin: 0 0 16px; font-size: 16px; }
.node-sync-side label { display: grid; gap: 6px; margin-bottom: 14px; }
.node-sync-actions { display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0; }
.node-sync-create { display: grid; gap: 8px; margin-top: 12px; }
.node-sync-notes, .node-sync-side small { opacity: .8; font-size: 13px; }
.node-sync-error { color: var(--theme-panel-settings-error-text, #dc4545); overflow-wrap: anywhere; }
.node-sync-result dl { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; margin: 0 0 18px; }
.node-sync-result dt { font-size: 12px; opacity: .75; }
.node-sync-result dd { margin: 4px 0 0; font-weight: 600; }
.node-sync-result details { overflow-wrap: anywhere; }
@media (max-width: 800px) { .node-sync-sides { grid-template-columns: 1fr; } .node-sync-panel { padding: 12px; } .node-sync-result dl { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
