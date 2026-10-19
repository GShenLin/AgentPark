<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from 'vue'
import { loadGraph, type WorkspaceBootstrap } from './api'
import { useGlobalState } from './composables/useGlobalState'
import { subscribeAppEvents } from './composables/useAppEventStream'
import { useAgentBoard } from './components/agent-board/useAgentBoard'
import { AgentBoardKey } from './components/agent-board/context'
import { nodeCardHeight, nodeCardWidth } from './components/agent-board/boardModel'
import NodeCardItem from './components/agent-board/NodeCardItem.vue'
import NodeFloatingNote from './components/agent-board/NodeFloatingNote.vue'
import NodeContextMenu from './components/agent-board/NodeContextMenu.vue'
import NodeWindowConversation from './components/NodeWindowConversation.vue'
import ActionButton from './components/ActionButton.vue'
import AppErrorToast from './components/AppErrorToast.vue'
import { createNodeWindowDrag } from './nodeWindowDrag'

const props = defineProps<{ bootstrap: WorkspaceBootstrap }>()
const bridge = window.agentParkNodeWindow
if (!bridge) throw new Error('Node window host is required.')
const host = bridge
const drag = createNodeWindowDrag(host)
const target = reactive({ ...host.target })
const ready = ref(false)
const initialized = ref(false)
const configOpen = ref(false)
const openingBrowser = ref(false)
const board = useAgentBoard({ ready, initialNodes: props.bootstrap.nodes, boardLayoutDefaults: props.bootstrap.board_layout, clipboardShortcuts: false })
provide(AgentBoardKey, board)
const state = useGlobalState()
const node = computed(() => board.nodes.value.find(item => item.id === target.nodeId))
const note = computed(() => board.nodeNotes.value[target.nodeId]?.trim() || '')
const noteArea = ref<HTMLElement | null>(null)
let noteObserver: ResizeObserver | null = null
let lastNoteHeight = -1
const menu = ref<InstanceType<typeof NodeContextMenu> | null>(null)
const startupError = ref('')
const stopIdentityEvents = subscribeAppEvents(event => {
  if (event.event !== 'node_renamed' || event.graph_id !== target.graphId || event.old_node_id !== target.nodeId) return
  if (typeof event.new_node_id !== 'string' || !event.new_node_id.trim()) return
  target.nodeId = event.new_node_id
  void host.retarget(target.nodeId).catch(report)
})

function report(error: unknown) { state.lastError.value = error instanceof Error ? error.message : String(error) }

async function openInBrowser() {
  if (openingBrowser.value) return
  openingBrowser.value = true
  try {
    await host.openInBrowser()
    menu.value?.closeMenu()
  } catch (error) { report(error) }
  finally { openingBrowser.value = false }
}

async function fitCardNote(force = false) {
  if (!node.value) return
  await nextTick()
  // Measure rendered, wrapped text rather than estimating from character count.
  const noteHeight = note.value && noteArea.value ? Math.min(240, Math.ceil(noteArea.value.scrollHeight)) + 8 : 0
  if (!force && noteHeight === lastNoteHeight) return
  lastNoteHeight = noteHeight
  await host.setMode('card', Math.max(420, nodeCardWidth(node.value)) + 24, Math.max(460, nodeCardHeight(node.value)) + 38 + noteHeight, noteHeight)
}

function onKey(event: KeyboardEvent) {
  if (event.key !== 'Escape' || event.defaultPrevented) return
  if (document.querySelector('[role="dialog"][aria-modal="true"]')) return
  if (configOpen.value) configOpen.value = false
}

watch(node, current => {
  const unavailable = '节点已删除或已移出当前画布。请关闭窗口后从新位置弹出。'
  if (current) {
    document.title = `${current.name} · AgentPark`
    if (state.lastError.value === unavailable) state.lastError.value = null
  } else if (initialized.value) state.lastError.value = unavailable
})

watch(note, () => {
  if (initialized.value) void fitCardNote().catch(report)
}, { flush: 'post' })

onMounted(async () => {
  document.documentElement.classList.add('node-window-document')
  window.addEventListener('keydown', onKey)
  window.addEventListener('blur', drag.cancel)
  try {
    state.providers.value = props.bootstrap.providers
    state.availableTools.value = props.bootstrap.tools
    const graph = await loadGraph(target.graphId)
    state.currentGraphId.value = target.graphId
    state.currentGraphName.value = graph.name || target.graphId
    state.currentGraphWorkingPath.value = graph.working_path || ''
    state.memoryMode.value = 'graph'
    state.graphLoadRequest.value = graph
    ready.value = true
    await nextTick()
    await board.refreshNodeConfigsAndMemory()
    if (!node.value) throw new Error('找不到要弹出的节点。')
    await board.selectAndFocusNode(target.nodeId, { focusViewport: false })
    await fitCardNote(true)
    initialized.value = true
    noteObserver = new ResizeObserver(() => { void fitCardNote().catch(report) })
    if (noteArea.value) noteObserver.observe(noteArea.value)
    host.ready()
  } catch (error) {
    startupError.value = error instanceof Error ? error.message : String(error)
    host.fail(startupError.value)
  }
})
onBeforeUnmount(() => {
  stopIdentityEvents()
  noteObserver?.disconnect()
  drag.cancel()
  window.removeEventListener('blur', drag.cancel)
  window.removeEventListener('keydown', onKey)
  document.documentElement.classList.remove('node-window-document')
})
</script>

<template>
  <main class="node-window-workspace" :class="{ 'has-note': !!note }">
    <aside v-show="note" ref="noteArea" class="node-window-note" aria-label="节点注释">
      <NodeFloatingNote :note="note" flow />
    </aside>
    <section class="node-window-card"
      @pointerdown.capture="drag.down" @pointermove="drag.move" @pointerup="drag.up"
      @pointercancel="drag.up" @lostpointercapture="drag.up" @click.capture="drag.click"
      @contextmenu.prevent="node && menu?.openAt({ x: $event.clientX, y: $event.clientY }, node.id)">
      <NodeCardItem v-if="node" :node="node" detached @minimize="host.minimize" @close="host.close">
        <template #content>
          <NodeWindowConversation v-if="initialized" :graphs="bootstrap.graphs" :graph-profiles="bootstrap.graph_profiles"
            :settings-open="configOpen" @close-settings="configOpen = false" />
          <div v-else class="node-window-status">{{ startupError || '正在加载对话…' }}</div>
        </template>
      </NodeCardItem>
      <div v-else class="node-window-status">{{ startupError || (initialized ? '节点已不可用' : '正在加载节点…') }}</div>
    </section>
    <NodeContextMenu ref="menu">
      <template #default="{ closeMenu }">
        <ActionButton variant="menu" :disabled="!initialized || openingBrowser" @click="openInBrowser">{{ openingBrowser ? '正在打开浏览器…' : '在浏览器中打开此节点' }}</ActionButton>
        <ActionButton variant="menu" :disabled="!initialized" @click="configOpen = true; closeMenu()">节点设置</ActionButton>
      </template>
    </NodeContextMenu>
    <AppErrorToast :message="state.lastError.value" placement="desktop" @dismiss="state.lastError.value = null" />
  </main>
</template>

<style src="./styles/nodeWindow.css"></style>
