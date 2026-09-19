<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { callPeer, type PeerConversation, type PeerNode } from '../../peerNetworkApi'
import { createBrowserUuid } from '../../utils/browserId'

const props = defineProps<{ peerId: string; peerName: string }>()
const graphs = ref<{ id: string; name: string }[]>([])
const nodes = ref<PeerNode[]>([])
const graphId = ref('')
const nodeId = ref('')
const conversation = ref<PeerConversation | null>(null)
const text = ref('')
const messageId = ref(createBrowserUuid())
const busy = ref(false)
const error = ref('')
const receipt = ref('')
const selectedNode = computed(() => nodes.value.find(n => n.id === nodeId.value))
let generation = 0

async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await action() } catch (cause) { error.value = String(cause) } finally { busy.value = false }
}
async function loadGraphs() {
  const epoch = generation
  const result = await callPeer<{ graphs: { id: string; name: string }[] }>(props.peerId, { operation: 'graphs' })
  if (epoch === generation) graphs.value = result.graphs
}
async function loadNodes() {
  nodes.value = []; nodeId.value = ''; conversation.value = null
  if (!graphId.value) return
  const epoch = generation
  const result = await callPeer<{ nodes: PeerNode[] }>(props.peerId, { operation: 'nodes', graph_id: graphId.value })
  if (epoch === generation) nodes.value = result.nodes
}
async function loadConversation() {
  if (!nodeId.value) return
  const epoch = generation
  const result = await callPeer<PeerConversation>(props.peerId, {
    operation: 'conversation', graph_id: graphId.value, node_id: nodeId.value,
  })
  if (epoch === generation) conversation.value = result
}
async function send() {
  const result = await callPeer<{ duplicate: boolean }>(props.peerId, {
    operation: 'message', graph_id: graphId.value, node_id: nodeId.value,
    text: text.value, message_id: messageId.value,
  })
  receipt.value = result.duplicate ? '这条消息已经送达，没有重复入队。' : '消息已进入对方节点队列，等待执行。'
  text.value = ''; messageId.value = createBrowserUuid()
}
async function stop() {
  await callPeer(props.peerId, { operation: 'control', action: 'stop', graph_id: graphId.value, node_id: nodeId.value })
  receipt.value = '已请求停止对方节点。'
  await loadConversation()
}
watch(() => props.peerId, () => {
  generation++; graphs.value = []; nodes.value = []; graphId.value = ''; nodeId.value = ''
  conversation.value = null; receipt.value = ''; text.value = ''; messageId.value = createBrowserUuid()
}, { immediate: true })
watch(text, () => { messageId.value = createBrowserUuid() })
</script>

<template>
  <section class="workspace">
    <h3>{{ peerName }} · 远程工作区</h3>
    <p>查看已共享的节点和最近对话，向节点发送消息，或停止当前执行。权限由对方设备控制。</p>
    <button :disabled="busy" @click="run(loadGraphs)">加载共享画板</button>
    <label>画板
      <select v-model="graphId" :disabled="busy" @change="run(loadNodes)">
        <option value="">选择画板</option><option v-for="g in graphs" :key="g.id" :value="g.id">{{ g.name }}</option>
      </select>
    </label>
    <label>节点
      <select v-model="nodeId" :disabled="busy" @change="run(loadConversation)">
        <option value="">选择节点</option><option v-for="n in nodes" :key="n.id" :value="n.id">{{ n.name }} · {{ n.state }}</option>
      </select>
    </label>
    <div v-if="selectedNode">
      <button :disabled="busy" @click="run(loadConversation)">刷新对话</button>
      <button :disabled="busy" @click="run(stop)">停止节点</button>
      <p v-if="conversation">状态：{{ conversation.state }} · {{ conversation.history_complete ? '完整历史' : '最近的对话' }}</p>
      <pre v-if="conversation">{{ conversation.text }}{{ conversation.live_message ? '\n' + conversation.live_message : '' }}</pre>
      <textarea v-model="text" :disabled="busy" maxlength="32000" rows="4" placeholder="向这个节点发送消息" />
      <button :disabled="busy || !text.trim()" @click="run(send)">发送消息</button>
    </div>
    <p v-if="receipt" role="status">{{ receipt }}</p><p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.workspace { display: grid; gap: 12px; border-top: 1px solid var(--border-color, #7775); padding-top: 18px; }
h3, p { margin: 0; } label { display: flex; gap: 12px; align-items: center; }
select, textarea { background: var(--bg-input, transparent); color: inherit; border: 1px solid #7777; padding: 8px; border-radius: 6px; }
textarea { box-sizing: border-box; width: 100%; margin: 12px 0; }
button { cursor: pointer; padding: 7px 12px; margin-right: 8px; } button:disabled { cursor: default; opacity: .5; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 450px; overflow: auto; padding: 12px; background: #7771; }
[role=alert] { color: #e56b6b; }
</style>
