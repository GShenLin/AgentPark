<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useMobileWorkspace } from './useMobileWorkspace'
import type { MessageEnvelope, MessagePart, MobileNode } from '../api'

const workspace = useMobileWorkspace()
const draft = ref('')
const feedRef = ref<HTMLElement | null>(null)

const headerTitle = computed(() => {
  if (workspace.view.value === 'pcs') return '选择 PC'
  if (workspace.view.value === 'graphs') return workspace.selectedPc.value?.name || '选择 Graph'
  if (workspace.view.value === 'nodes') return workspace.selectedGraph.value?.display_name || '选择节点'
  return workspace.selectedNode.value?.name || workspace.selectedNode.value?.id || '节点消息'
})

const messages = computed(() => workspace.conversation.value?.messages || [])

function nodeStateLabel(node: MobileNode) {
  const state = String(node.state || 'idle')
  if (state === 'working') return '工作中'
  if (state === 'stop') return '已停止'
  return '空闲'
}

function nodeStateClass(node: MobileNode) {
  const state = String(node.state || 'idle')
  if (state === 'working') return 'state-working'
  if (state === 'stop') return 'state-stop'
  return 'state-idle'
}

function messageText(message: MessageEnvelope) {
  return (message.parts || [])
    .filter((part) => part.type === 'text')
    .map((part: MessagePart) => String((part as { type: 'text'; text: string }).text || ''))
    .join('\n')
    .trim()
}

function messageRoleClass(message: MessageEnvelope) {
  const role = String(message.role || '').toLowerCase()
  if (role.includes('user')) return 'from-user'
  if (role.includes('tool')) return 'from-tool'
  return 'from-node'
}

async function sendDraft() {
  const text = draft.value.trim()
  if (!text) return
  draft.value = ''
  await workspace.sendMessage(text)
  await nextTick()
  scrollFeedToBottom()
}

function scrollFeedToBottom() {
  const el = feedRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

watch(messages, () => nextTick(scrollFeedToBottom))

onMounted(() => {
  void workspace.loadPcs()
})
</script>

<template>
  <div class="mobile-shell">
    <header class="mobile-header">
      <button v-if="workspace.view.value === 'graphs'" class="icon-btn" type="button" aria-label="返回 PC" @click="workspace.backToPcs">‹</button>
      <button v-else-if="workspace.view.value === 'nodes'" class="icon-btn" type="button" aria-label="返回 Graph" @click="workspace.backToGraphs">‹</button>
      <button v-else-if="workspace.view.value === 'chat'" class="icon-btn" type="button" aria-label="返回节点" @click="workspace.backToNodes">‹</button>
      <div v-else class="header-spacer"></div>
      <div class="header-title">{{ headerTitle }}</div>
      <button class="icon-btn" type="button" aria-label="刷新" @click="workspace.refreshCurrent">↻</button>
    </header>

    <main class="mobile-main">
      <div v-if="workspace.error.value" class="mobile-error">{{ workspace.error.value }}</div>
      <div v-if="workspace.loading.value" class="loading-line">Loading...</div>

      <section v-if="workspace.view.value === 'pcs'" class="mobile-list">
        <button v-for="pc in workspace.pcs.value" :key="pc.id" class="list-row pc-row" type="button" @click="workspace.selectPc(pc)">
          <span class="row-main">{{ pc.name }}</span>
          <span class="row-sub">{{ pc.instance_count }} instance</span>
          <span class="row-arrow">›</span>
        </button>
      </section>

      <section v-else-if="workspace.view.value === 'graphs'" class="mobile-list">
        <div v-for="instance in workspace.graphInstances.value" :key="instance.id" class="instance-group">
          <div class="instance-head">
            <span>{{ instance.name }}</span>
            <small>{{ instance.path }}</small>
          </div>
          <button v-for="graph in instance.graphs" :key="graph.id" class="list-row graph-row" type="button" @click="workspace.selectGraph(graph)">
            <span class="row-main">{{ graph.display_name }}</span>
            <span class="row-sub">{{ graph.updated_at || 'not saved yet' }}</span>
            <span class="row-arrow">›</span>
          </button>
        </div>
      </section>

      <section v-else-if="workspace.view.value === 'nodes'" class="mobile-list">
        <button v-for="node in workspace.nodes.value" :key="node.id" class="list-row node-row" type="button" @click="workspace.selectNode(node)">
          <span class="node-status" :class="nodeStateClass(node)"></span>
          <span class="row-body">
            <span class="row-main">{{ node.name || node.id }}</span>
            <span class="row-sub">{{ node.type_id }} · {{ nodeStateLabel(node) }}</span>
            <span v-if="node.last_message" class="row-last">{{ node.last_message }}</span>
          </span>
          <span v-if="node.pending_count" class="pending-pill">{{ node.pending_count }}</span>
          <span class="row-arrow">›</span>
        </button>
      </section>

      <section v-else class="chat-view">
        <div class="node-summary">
          <span class="node-status" :class="workspace.selectedNode.value ? nodeStateClass(workspace.selectedNode.value) : 'state-idle'"></span>
          <span>{{ workspace.selectedNode.value ? nodeStateLabel(workspace.selectedNode.value) : '' }}</span>
          <span v-if="workspace.selectedNode.value?.last_runtime_event" class="activity-text">
            {{ String(workspace.selectedNode.value.last_runtime_event.name || workspace.selectedNode.value.last_runtime_event.type || '') }}
          </span>
        </div>

        <div ref="feedRef" class="chat-feed">
          <div v-if="messages.length === 0" class="empty-chat">暂无消息</div>
          <article v-for="(message, index) in messages" :key="String(message.id || index)" class="bubble" :class="messageRoleClass(message)">
            <div class="bubble-meta">{{ String(message.role || 'assistant') }}</div>
            <div class="bubble-text">{{ messageText(message) || '[structured message]' }}</div>
          </article>
        </div>

        <form class="composer" @submit.prevent="sendDraft">
          <textarea v-model="draft" rows="2" placeholder="输入消息" :disabled="workspace.sending.value"></textarea>
          <button type="submit" :disabled="workspace.sending.value || !draft.trim()">发送</button>
        </form>
      </section>
    </main>
  </div>
</template>

<style scoped>
.mobile-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #08111f;
}

.mobile-header {
  height: 54px;
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) 42px;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(8, 17, 31, 0.95);
}

.header-title {
  min-width: 0;
  text-align: center;
  font-weight: 700;
  font-size: 15px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.icon-btn {
  width: 36px;
  height: 36px;
  padding: 0;
  border-radius: 8px;
  font-size: 24px;
  line-height: 1;
}

.header-spacer {
  width: 36px;
}

.mobile-main {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px;
  overflow: hidden;
}

.mobile-list {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
  padding-bottom: 12px;
}

.list-row {
  width: 100%;
  min-height: 72px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 12px;
  text-align: left;
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
}

.node-row {
  grid-template-columns: 12px minmax(0, 1fr) auto auto;
}

.row-body,
.row-main,
.row-sub,
.row-last {
  min-width: 0;
  display: block;
}

.row-main {
  color: rgba(248, 250, 252, 0.96);
  font-weight: 700;
  font-size: 15px;
  overflow-wrap: anywhere;
}

.row-sub,
.row-last,
.instance-head small,
.activity-text {
  color: rgba(148, 163, 184, 0.92);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.row-last {
  margin-top: 4px;
  color: rgba(203, 213, 225, 0.9);
}

.row-arrow {
  color: rgba(125, 211, 252, 0.88);
  font-size: 24px;
}

.instance-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.instance-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px 2px 0;
  color: rgba(226, 232, 240, 0.96);
  font-size: 13px;
  font-weight: 700;
}

.node-status {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.75);
}

.state-working {
  background: #22c55e;
}

.state-stop {
  background: #f87171;
}

.state-idle {
  background: #38bdf8;
}

.pending-pill {
  min-width: 22px;
  height: 22px;
  padding: 0 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(14, 165, 233, 0.22);
  color: rgba(224, 242, 254, 0.96);
  font-size: 12px;
  font-weight: 700;
}

.chat-view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.node-summary {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.58);
  font-size: 13px;
}

.chat-feed {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
  padding: 4px 2px;
}

.bubble {
  max-width: 88%;
  padding: 9px 11px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(15, 23, 42, 0.76);
}

.from-user {
  align-self: flex-end;
  background: rgba(14, 165, 233, 0.24);
}

.from-node,
.from-tool {
  align-self: flex-start;
}

.from-tool {
  background: rgba(129, 140, 248, 0.18);
}

.bubble-meta {
  margin-bottom: 4px;
  color: rgba(148, 163, 184, 0.92);
  font-size: 11px;
}

.bubble-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.5;
  font-size: 14px;
}

.composer {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 64px;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(148, 163, 184, 0.14);
}

.composer textarea {
  width: 100%;
  resize: none;
  min-height: 44px;
  max-height: 110px;
  padding: 9px 10px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  color: rgba(248, 250, 252, 0.96);
  background: rgba(15, 23, 42, 0.78);
  font-family: inherit;
  font-size: 14px;
}

.composer button {
  height: 44px;
  align-self: end;
}

.mobile-error,
.loading-line,
.empty-chat {
  flex: 0 0 auto;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
}

.mobile-error {
  margin-bottom: 10px;
  border: 1px solid rgba(248, 113, 113, 0.45);
  background: rgba(127, 29, 29, 0.32);
  color: rgba(254, 226, 226, 0.96);
}

.loading-line,
.empty-chat {
  color: rgba(148, 163, 184, 0.95);
}
</style>
