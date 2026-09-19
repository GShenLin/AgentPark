<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, provide, ref } from 'vue'
import { connectBoard } from './connection'
import { attachBoardWorker } from './workerBridge'
import { cloudBoardRestart } from './restartContext'
import { restartBoardConnection } from './restartConnection'
import { useBoardReconnect } from './useBoardReconnect'

interface Device { peer_id: string; name: string; connected_at: string; portal_board: boolean; stun_urls: string[]; state: string }
interface Enrollment { peer_id: string; name: string; state: 'pending' | 'approved' | 'rejected'; requested_at: number }
const BoardApp = defineAsyncComponent(() => import('../App.vue'))
const devices = ref<Device[]>([])
const enrollments = ref<Enrollment[]>([])
const pending = computed(() => enrollments.value.filter(device => device.state === 'pending'))
const password = ref('')
const signedIn = ref(false)
const busy = ref(false)
const error = ref('')
const state = ref('')
const boardReady = ref(false)
const restarting = ref(false)
let restartAbort: AbortController | undefined
const selectedId = /^\/board\/([a-f0-9]{64})$/.exec(location.pathname)?.[1] || ''
const selected = computed(() => devices.value.find(device => device.peer_id === selectedId))
let connection: Awaited<ReturnType<typeof connectBoard>> | undefined
let detachWorker: (() => void) | undefined
let timer: ReturnType<typeof setInterval> | undefined
let disposed = false
provide(cloudBoardRestart, restartBoard)
useBoardReconnect({
  ready: boardReady,
  canReconnect: () => !!selectedId && signedIn.value && !busy.value && !restarting.value && !disposed,
  reconnect: reconnectBoard,
  onError: cause => { error.value = String(cause) },
})

function disconnected(message: string) {
  boardReady.value = false
  if (!restarting.value && !disposed) error.value = message
}

async function restartBoard(): Promise<{ ok: boolean }> {
  if (restarting.value) throw new Error('设备正在重启，请稍候。')
  if (!connection || !boardReady.value) throw new Error('请先连接设备。')
  restarting.value = true; boardReady.value = false; error.value = ''
  state.value = '正在读取设备重启状态…'
  restartAbort = new AbortController()
  detachWorker?.(); detachWorker = undefined
  try {
    connection = await restartBoardConnection(connection, async signal => {
      await loadDevices()
      if (!signedIn.value) throw new Error('登录已过期，请重新登录。')
      const device = selected.value
      if (!device) throw new Error('设备尚未重新上线。')
      if (!device.portal_board) throw new Error('设备未开放 Board。')
      return connectBoard(device.peer_id, device.stun_urls, disconnected, signal)
    }, message => { state.value = message }, restartAbort.signal)
    if (disposed) { connection.close(); throw new Error('页面已关闭。') }
    detachWorker = await attachBoardWorker(connection.rpc)
    state.value = await connection.describeTransport(); boardReady.value = true
    return { ok: true }
  } catch (cause) {
    connection?.close(); connection = undefined
    error.value = String(cause); state.value = '重启未确认完成'
    throw cause
  } finally { restarting.value = false; restartAbort = undefined }
}

async function restartFromHeader() {
  try { await restartBoard() } catch (cause) { error.value = String(cause) }
}

async function reconnectBoard() {
  if (busy.value || restarting.value || disposed) return
  detachWorker?.(); detachWorker = undefined
  connection?.close(); connection = undefined
  boardReady.value = false
  await initialize()
}

async function loadDevices() {
  const response = await fetch('/portal/api/devices', { cache: 'no-store' })
  if (response.status === 401) {
    signedIn.value = false
    restartAbort?.abort(new Error('登录已过期，请重新登录。'))
    return
  }
  if (!response.ok) throw new Error(await response.text())
  const data = await response.json()
  if (!Array.isArray(data.devices)) throw new Error('设备列表格式无效。')
  if (!disposed) { devices.value = data.devices; signedIn.value = true }
  if (!selectedId) {
    const requests = await fetch('/portal/api/enrollments', { cache: 'no-store' })
    if (!requests.ok) throw new Error(await requests.text())
    const listing = await requests.json()
    if (!Array.isArray(listing.devices)) throw new Error('接入申请格式无效。')
    if (!disposed) enrollments.value = listing.devices
  }
}
async function decideEnrollment(device: Enrollment, state: 'approved' | 'rejected') {
  busy.value = true; error.value = ''
  try {
    const response = await fetch(`/portal/api/enrollments/${device.peer_id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ state }),
    })
    if (!response.ok) throw new Error(await response.text())
    await loadDevices()
  } catch (cause) { error.value = String(cause) } finally { busy.value = false }
}
async function openBoard() {
  if (!selectedId || !signedIn.value) return
  const device = selected.value
  if (!device) throw new Error('这台设备当前不在线，请返回设备列表。')
  if (!device.portal_board) throw new Error('这台设备未开放云端 Board 访问。')
  state.value = '正在连接设备，优先直连，必要时使用中继…'
  connection = await connectBoard(device.peer_id, device.stun_urls, disconnected)
  if (disposed) { connection.close(); return }
  try { detachWorker = await attachBoardWorker(connection.rpc) }
  catch (cause) { connection.close(); connection = undefined; throw cause }
  state.value = await connection.describeTransport(); boardReady.value = true
}
async function initialize() {
  error.value = ''; busy.value = true
  try { await loadDevices(); await openBoard() } catch (cause) { error.value = String(cause); state.value = '连接未完成' } finally { busy.value = false }
}
async function login() {
  busy.value = true; error.value = ''
  try {
    const response = await fetch('/portal/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: password.value }) })
    password.value = ''
    if (!response.ok) throw new Error(await response.text())
    await loadDevices(); await openBoard()
  } catch (cause) { error.value = String(cause) } finally { busy.value = false }
}
async function logout() {
  const response = await fetch('/portal/api/logout', { method: 'POST' })
  if (!response.ok) { error.value = await response.text(); return }
  connection?.close(); location.href = '/'
}
onMounted(async () => {
  await initialize()
  if (!disposed && !selectedId) timer = setInterval(() => {
    if (signedIn.value && !busy.value) void loadDevices().catch(cause => { error.value = String(cause) })
  }, 5000)
})
onUnmounted(() => { disposed = true; restartAbort?.abort(); if (timer) clearInterval(timer); detachWorker?.(); connection?.close() })
</script>

<template>
  <main v-if="!signedIn" class="portal login">
    <div class="brand">AgentPark <span>设备中心</span></div>
    <form class="login-card" @submit.prevent="login">
      <h1>连接你的 AgentPark</h1>
      <p>登录后查看在线设备，直接进入设备的 Board。</p>
      <label for="portal-password">管理员密码</label>
      <input id="portal-password" v-model="password" type="password" autocomplete="current-password" required :disabled="busy">
      <button :disabled="busy">{{ busy ? '正在连接…' : '登录设备中心' }}</button>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </form>
  </main>
  <div v-else-if="selectedId" class="portal-board">
    <header class="board-header">
      <a href="/">← 设备列表</a><strong>{{ selected?.name || 'AgentPark' }}</strong>
      <span :class="{ online: boardReady }">{{ restarting ? '重启中' : boardReady ? state : '未连接' }}</span>
      <button :disabled="!boardReady || restarting" @click="restartFromHeader">{{ restarting ? '重启中…' : '更新并重启' }}</button>
      <button @click="logout">退出登录</button>
    </header>
    <div v-if="error" class="connection-message" role="alert"><p>{{ error }}</p><button :disabled="busy || restarting" @click="reconnectBoard">重新连接</button> <a href="/">返回设备列表</a></div>
    <BoardApp v-else-if="boardReady" />
    <div v-else class="connection-message"><h2>{{ restarting ? '正在更新并重启设备' : '正在打开设备 Board' }}</h2><p>{{ state }}</p><p>{{ restarting ? '重启只请求一次，页面会等待新进程启动并自动恢复连接。' : '优先直连；直连不可用时通过云端中继传输，数据仍在浏览器与设备之间端到端加密。' }}</p></div>
  </div>
  <main v-else class="portal">
    <header><div class="brand">AgentPark <span>设备中心</span></div><button @click="logout">退出登录</button></header>
    <section class="intro"><p class="eyebrow">随时连接你的设备</p><h1>在线设备 <span>{{ devices.length }}</span></h1><p>这里列出当前已连接到协调服务的设备。选择一台，打开它的 AgentPark Board。</p></section>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <section v-if="pending.length">
      <h2>待确认的新设备 · {{ pending.length }}</h2>
      <p>与本机设置中的设备身份核对后允许接入。确认前，这些设备不能访问设备列表或建立连接。</p>
      <div class="device-grid">
        <article v-for="device in pending" :key="device.peer_id" class="device-card">
          <h2>{{ device.name }}</h2><p>{{ new Date(device.requested_at * 1000).toLocaleString() }}</p>
          <code>{{ device.peer_id }}</code>
          <button :disabled="busy" @click="decideEnrollment(device, 'approved')">允许这台设备</button>
          <button :disabled="busy" @click="decideEnrollment(device, 'rejected')">拒绝</button>
        </article>
      </div>
    </section>
    <div class="device-grid">
      <article v-for="device in devices" :key="device.peer_id" class="device-card">
        <div class="device-state"><span class="dot"></span>已连接云端</div>
        <h2>{{ device.name }}</h2>
        <p>接入时间 {{ new Date(device.connected_at).toLocaleString() }}</p>
        <code>{{ device.peer_id }}</code>
        <a v-if="device.portal_board" :href="`/board/${device.peer_id}`" class="open-board">打开 Board <span>↗</span></a>
        <p v-else class="disabled">此设备未开放云端 Board</p>
      </article>
    </div>
    <section v-if="!devices.length" class="empty"><h2>还没有在线设备</h2><p>在设备的 AgentPark「设置 → 设备互联」中填写本服务器 IP，勾选启用，再在此页确认接入。</p></section>
    <footer>设备列表每 5 秒刷新。Board 优先使用 P2P 直连，必要时通过云端 TURN 中继连接。</footer>
  </main>
</template>

<style scoped>
.portal {
  height: 100vh;
  height: 100dvh;
  overflow-y: auto;
  overflow-x: hidden;
  box-sizing: border-box;
  background: #10171d;
  color: #eaf1f4;
  padding: 36px max(28px, calc((100vw - 1180px) / 2));
  font-family: system-ui, sans-serif;
}
header, .board-header { display: flex; justify-content: space-between; align-items: center; gap: 18px; }
.brand { font-size: 24px; font-weight: 750; letter-spacing: -.8px; }.brand span { color: #92a3af; font-size: 14px; margin-left: 12px; font-weight: 400; }
.intro { margin: 75px 0 36px; }.eyebrow { color: #8cdabb !important; font-size: 13px; letter-spacing: 2px; }
h1 { font-size: 36px; letter-spacing: -1px; margin: 10px 0 14px; }h1 span { font-size: 20px; color: #8cdabb; margin-left: 10px; }
p, footer { line-height: 1.7; color: #9caeba; }button, .open-board { cursor: pointer; background: #a8e8cc; color: #10231d; border: 0; border-radius: 7px; padding: 11px 17px; font-weight: 650; }
header button { background: transparent; color: #bac8d1; border: 1px solid #3c4b55; }button:disabled { opacity: .5; cursor: default; }
.device-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px; }
.device-card { background: #18232c; border: 1px solid #2c3b47; border-radius: 12px; padding: 25px; display: flex; flex-direction: column; gap: 10px; }
.device-state { font-size: 12px; color: #a8e8cc; }.dot { display: inline-block; width: 7px; height: 7px; background: #8bddb6; border-radius: 50%; margin-right: 7px; }
h2 { margin: 12px 0 0; font-size: 22px; }.device-card p { margin: 0; font-size: 12px; }code { color: #94a6b2; overflow-wrap: anywhere; font-size: 11px; line-height: 1.6; margin-bottom: 14px; }
.open-board { text-decoration: none; display: flex; justify-content: space-between; margin-top: auto; }.disabled { padding: 12px 0; }
footer { font-size: 12px; padding: 38px 0; }.empty { padding: 50px; text-align: center; border: 1px dashed #354854; border-radius: 12px; }
.login-card { max-width: 440px; margin: 100px auto 0; display: grid; gap: 14px; }.login-card h1 { font-size: 30px; }.login-card p { margin: 0 0 12px; }
input { background: #19262f; color: #eaf1f4; border: 1px solid #435663; padding: 13px; border-radius: 7px; font: inherit; }.error { color: #ffafa7 !important; overflow-wrap: anywhere; }
.portal-board { height: 100vh; height: 100dvh; overflow: hidden; display: flex; flex-direction: column; }.board-header { min-height: 48px; padding: 0 18px; background: #132029; color: #eaf1f4; font-size: 13px; flex-shrink: 0; }.board-header a { color: #a8e8cc; text-decoration: none; }.board-header button { padding: 5px 10px; }.online { color: #9ddfbf; }
.portal-board :deep(.app-shell) { flex: 1; min-height: 0; height: auto; }.connection-message { padding: 60px; text-align: center; }.connection-message a { color: #48aa82; }
@media (max-width: 760px) { .portal { padding: 24px 18px; }.intro { margin-top: 42px; }.board-header { min-height: 40px; padding: 0 10px; gap: 8px; font-size: 11px; }.board-header strong { min-width: 0; max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.board-header a, .board-header button, .board-header span { flex-shrink: 0; }.portal-board :deep(.mobile-main) { padding-bottom: max(12px, env(safe-area-inset-bottom)); } }
</style>
