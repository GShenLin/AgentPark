<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { peerApi, type PeerGrant, type PeerSettings, type PeerStatus } from '../../peerNetworkApi'
import PeerWorkspacePanel from './PeerWorkspacePanel.vue'

const status = ref<PeerStatus | null>(null)
const settings = ref<PeerSettings>({ enabled: true, server_ip: '203.0.113.10', display_name: '' })
const enrollmentLabel = computed(() => {
  if (!settings.value.enabled) return '未启用'
  if (!settings.value.server_ip.trim()) return '请填写鉴权服务器 IP'
  if (status.value?.coordinator_connected) return '已连接设备中心'
  if (status.value?.enrollment_state === 'pending') return '等待云端确认此设备'
  if (status.value?.enrollment_state === 'rejected') return '云端已拒绝此设备的接入申请'
  return '正在连接设备中心'
})
const portalUrl = computed(() => settings.value.server_ip ? `https://${settings.value.server_ip.includes(':') ? `[${settings.value.server_ip}]` : settings.value.server_ip}/` : '')
const error = ref('')
const notice = ref('')
const busy = ref(false)
const grant = ref<PeerGrant>({ peer_id: '', name: '', view: false, control: false, collaborate: false, graph_ids: [] })
const graphIds = ref('')
const selectedPeer = ref('')
const selected = computed(() => status.value?.peers.find(p => p.peer_id === selectedPeer.value))
let timer: ReturnType<typeof setInterval> | undefined
let disposed = false
let refreshing = false

async function load(initial = false) {
  if (refreshing) return
  refreshing = true
  try {
    const value = await peerApi<PeerStatus>()
    if (disposed) return
    status.value = value
    if (initial) settings.value = { ...value.settings, display_name: value.device_name }
  } finally { refreshing = false }
}
async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await action() } catch (cause) { error.value = String(cause) } finally { busy.value = false }
}
async function saveSettings() {
  if (!settings.value.display_name.trim()) throw new Error('请填写本机名称。')
  try { status.value = await peerApi<PeerStatus>('/settings', 'PUT', settings.value) }
  catch (cause) { if (status.value) settings.value.enabled = status.value.settings.enabled; throw cause }
  settings.value = { ...status.value.settings }; notice.value = settings.value.enabled ? '设置已保存，正在连接设备中心。首次接入请在云端确认此设备。' : '设置已保存，设备互联未启用。'
}
async function saveGrant() {
  status.value = await peerApi<PeerStatus>('/grants', 'PUT', {
    ...grant.value, graph_ids: graphIds.value.split(/[,，\s]+/).filter(Boolean),
  })
  notice.value = '已保存对这台设备的授权。对方也需要添加本机设备编号，并设置给本机的权限。'
}
function editPeer(peer: PeerGrant) { grant.value = { ...peer }; graphIds.value = peer.graph_ids.join(', ') }
async function connect(peer: string) { status.value = await peerApi<PeerStatus>(`/${peer}/connect`, 'POST', {}) }
async function revoke(peer: string) {
  status.value = await peerApi<PeerStatus>(`/${peer}`, 'DELETE')
  if (selectedPeer.value === peer) selectedPeer.value = ''
  notice.value = '已撤销授权并关闭与这台设备的连接。'
}
const stateLabel: Record<string, string> = { connected: '已连接', connecting: '正在连接', new: '正在协商', disconnected: '未连接', failed: '连接失败', closed: '已断开' }
onMounted(async () => {
  await run(() => load(true))
  if (!disposed) timer = setInterval(() => {
    if (!busy.value) void load().catch(cause => { if (!disposed) error.value = String(cause) })
  }, 5000)
})
onUnmounted(() => { disposed = true; if (timer) clearInterval(timer) })
</script>

<template>
  <div class="peer-network">
    <h3>设备互联</h3>
    <p>连接另一台 AgentPark，查看和操作共享节点，或让双方 Agent 互发消息。优先直连，必要时通过云端中继，业务数据保持端到端加密。</p>
    <p v-if="status">本机：{{ status.device_name }} · {{ enrollmentLabel }}</p>
    <p v-if="status?.error" role="alert">{{ status.error }}</p>
    <fieldset :disabled="busy">
      <legend>连接设置</legend>
      <label>本机名称<input v-model="settings.display_name" maxlength="100" placeholder="填写设备列表中显示的名称"></label>
      <label>鉴权服务器 IP<input v-model="settings.server_ip" placeholder="例如 203.0.113.10"></label>
      <label><input v-model="settings.enabled" type="checkbox" @change="run(saveSettings)">启用设备互联</label>
      <button :disabled="!status || !settings.display_name.trim()" @click="run(saveSettings)">保存设置</button>
      <p>首次接入需在云端确认一次，之后自动连接。启用后可从设备中心打开本机公开 Board。</p>
      <a v-if="portalUrl && status?.settings.server_ip === settings.server_ip" :href="portalUrl" target="_blank" rel="noopener noreferrer">打开云端设备中心 ↗</a>
      <details v-if="status"><summary>设备身份（供云端确认时核对）</summary><code>{{ status.peer_id }}</code></details>
    </fieldset>
    <p v-if="notice" role="status">{{ notice }}</p><p v-if="error" role="alert">{{ error }}</p>
    <details>
      <summary>设备之间的共享与 Agent 协作（可选）</summary>
    <fieldset :disabled="busy">
      <legend>添加设备与授权</legend>
      <label>对方设备编号<input v-model="grant.peer_id" maxlength="64"></label>
      <label>备注名称<input v-model="grant.name" maxlength="100"></label>
      <label>共享画板编号<input v-model="graphIds" placeholder="例如 default，多个用逗号分隔"></label>
      <p>以下权限是本机授予对方的权限，仅适用于列出的公开画板及其中的公开节点。留空不共享画板。</p>
      <div class="permissions">
        <label><input v-model="grant.view" type="checkbox">查看节点和对话</label>
        <label><input v-model="grant.control" type="checkbox">发送消息与停止节点</label>
        <label><input v-model="grant.collaborate" type="checkbox">Agent 消息协作</label>
      </div>
      <button @click="run(saveGrant)">保存设备授权</button>
    </fieldset>
    <article v-for="peer in status?.peers || []" :key="peer.peer_id">
      <strong>{{ peer.name }}</strong> · {{ stateLabel[peer.state] || peer.state }}
      <p><code>{{ peer.peer_id }}</code></p>
      <p v-if="peer.error && peer.state !== 'connected'">{{ peer.error }}</p>
      <button :disabled="busy" @click="editPeer(peer)">编辑授权</button>
      <button :disabled="busy || peer.state === 'connected'" @click="run(() => connect(peer.peer_id))">连接</button>
      <button :disabled="busy || peer.state !== 'connected'" @click="selectedPeer = peer.peer_id">打开远程工作区</button>
      <button :disabled="busy" @click="run(() => revoke(peer.peer_id))">撤销授权</button>
    </article>
    <PeerWorkspacePanel v-if="selected" :key="selected.peer_id" :peer-id="selected.peer_id" :peer-name="selected.name" />
    <p>Agent 协作：在需要协作的节点工具列表中启用 peer_network_tools。双方都要授权；收到消息后由目标 Agent 决定执行和回复。</p>
    </details>
  </div>
</template>

<style scoped>
.peer-network { display: grid; gap: 16px; max-width: 1000px; } h3, p { margin: 0; }
fieldset { display: grid; gap: 12px; border: 1px solid #7775; border-radius: 8px; padding: 16px; }
label { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
input:not([type=checkbox]), textarea { flex: 1; min-width: 180px; border: 1px solid #7777; border-radius: 6px; padding: 8px; background: transparent; color: inherit; }
.permissions { display: flex; gap: 16px; flex-wrap: wrap; }
button { cursor: pointer; padding: 7px 12px; margin-right: 8px; } button:disabled { opacity: .5; cursor: default; }
article { border: 1px solid #7775; padding: 14px; border-radius: 8px; display: block; } article p { margin: 8px 0; }
code { overflow-wrap: anywhere; user-select: all; } [role=alert] { color: #e56b6b; }
</style>
