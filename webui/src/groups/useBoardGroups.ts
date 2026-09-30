import { computed, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'
import { subscribeAppEvents } from '../composables/useAppEventStream'
import type { NodeCard } from '../components/agent-board/context'
import type { BoardGridSettings } from '../components/agent-board/boardGrid'
import { groupApi, type AgentGroup, type GroupBounds } from './groupApi'
import { boundsOverlap, groupAtPoint, groupBounds, nodeCenter, selectionGroup } from './groupGeometry'

export function useBoardGroups(options: {
  graphId: Ref<string | null>; nodes: Ref<NodeCard[]>; selectedIds: Ref<string[]>; grid: Ref<BoardGridSettings>
  ready?: Ref<boolean>; lastError: Ref<string | null>; board: Ref<HTMLElement | null>
}) {
  const groups = ref<AgentGroup[]>([])
  const activeId = ref<string | null>(null)
  const busy = ref(false)
  const active = computed(() => groups.value.find(group => group.id === activeId.value) ?? null)
  let epoch = 0
  let fetchVersion = 0
  let commandQueue: Promise<unknown> = Promise.resolve()
  let pendingCommands = 0
  const connectionReady = () => options.ready?.value !== false

  async function refresh() {
    const graph = options.graphId.value
    if (!graph || !connectionReady()) return
    const version = ++fetchVersion
    const capturedEpoch = epoch
    const result = await groupApi.list(graph)
    if (capturedEpoch !== epoch || version !== fetchVersion || graph !== options.graphId.value || !connectionReady()) return
    groups.value = result.groups
    if (activeId.value && !result.groups.some(group => group.id === activeId.value)) activeId.value = null
  }

  function perform(work: (graph: string, checkCurrent: () => void) => Promise<void>) {
    const graph = options.graphId.value
    if (!graph || !connectionReady()) return Promise.resolve(false)
    const capturedEpoch = epoch
    const checkCurrent = () => {
      if (capturedEpoch !== epoch || graph !== options.graphId.value || !connectionReady()) {
        throw new Error('当前图或连接已改变，未提交的分组操作已取消。')
      }
    }
    pendingCommands += 1
    busy.value = true
    const command = commandQueue.then(async () => {
      if (capturedEpoch !== epoch) return false
      try {
        checkCurrent()
        await work(graph, checkCurrent)
        if (capturedEpoch === epoch) await refresh()
        return true
      } catch (error) {
        if (capturedEpoch === epoch) options.lastError.value = String(error instanceof Error ? error.message : error)
        return false
      } finally {
        if (capturedEpoch === epoch) { pendingCommands -= 1; busy.value = pendingCommands > 0 }
      }
    })
    commandQueue = command
    return command
  }

  async function toggleSelection() {
    const ids = [...options.selectedIds.value]
    const nodes = options.nodes.value.filter(node => ids.includes(node.id)).map(node => ({ ...node, ui: { ...node.ui } }))
    const grid = { ...options.grid.value }
    await perform(async (graph, checkCurrent) => {
      if (!ids.length) return
      const current = await groupApi.list(graph)
      checkCurrent()
      const existing = selectionGroup(current.groups, ids)
      if (existing) { await groupApi.dissolve(graph, existing.id, existing.revision); return }
      if (current.groups.some(group => group.members.some(member => ids.includes(member.node_id)))) {
        throw new Error('所选 Agent 已在组内。框选该组全部成员后按 G 可以解除组队。')
      }
      if (nodes.some(node => node.typeId !== 'agent_node')) throw new Error('只能将 Agent 节点编入组。')
      const bounds = groupBounds(nodes, grid)
      if (current.groups.some(group => boundsOverlap(group.bounds, bounds))) throw new Error('新组边框与已有组重叠，请先把这些 Agent 移到空白区域。')
      await groupApi.create(graph, { name: `Group ${current.groups.length + 1}`, objective: '', bounds,
        members: nodes.map(node => ({ node_id: node.id, role: '' })) })
    })
  }

  async function dissolve(group: AgentGroup) {
    await perform(async graph => { await groupApi.dissolve(graph, group.id, group.revision) })
  }

  async function resize(group: AgentGroup, bounds: GroupBounds) {
    return perform(async graph => {
      await groupApi.configure(graph, group.id, { expected_revision: group.revision, bounds })
    })
  }

  async function afterNodeDrop(ids: string[]) {
    const positions = options.nodes.value.filter(node => ids.includes(node.id) && node.typeId === 'agent_node')
      .map(node => ({ id: node.id, center: nodeCenter(node, options.grid.value) }))
    await perform(async (graph, checkCurrent) => {
      const current = await groupApi.list(graph)
      checkCurrent()
      for (const { id, center } of positions) {
        checkCurrent()
        const source = current.groups.find(group => group.members.some(member => member.node_id === id)) ?? null
        const target = groupAtPoint(current.groups, center)
        if (source?.id === target?.id) continue
        await groupApi.move(graph, id, { expected_source: source?.id ?? null, target_group_id: target?.id ?? null })
      }
    })
  }

  function openAt(point: { x: number; y: number }) {
    try { activeId.value = groupAtPoint(groups.value, point)?.id ?? null }
    catch (error) { options.lastError.value = String(error instanceof Error ? error.message : error) }
  }

  function onKey(event: KeyboardEvent) {
    if (event.defaultPrevented || event.repeat || event.key.toLowerCase() !== 'g' || event.ctrlKey || event.metaKey || event.altKey) return
    const target = event.target as HTMLElement | null
    if (target?.closest('input, textarea, select, [contenteditable="true"], [role="dialog"], .modal')) return
    if (!options.board.value?.getClientRects().length || activeId.value || !options.selectedIds.value.length) return
    event.preventDefault()
    void toggleSelection()
  }

  function refreshOrReport() { void refresh().catch(error => { options.lastError.value = String(error.message || error) }) }
  const unsubscribe = subscribeAppEvents(event => {
    if (event.event === 'stream_gap' || event.event === 'stream_snapshot' ||
        (event.event === 'groups_changed' && event.graph_id === options.graphId.value)) refreshOrReport()
  })
  watch([options.graphId, () => options.ready?.value], ([graph], [previousGraph]) => {
    epoch += 1
    pendingCommands = 0
    busy.value = false
    if (graph !== previousGraph) { groups.value = []; activeId.value = null }
    refreshOrReport()
  }, { immediate: true })
  onMounted(() => window.addEventListener('keydown', onKey))
  onBeforeUnmount(() => { epoch += 1; unsubscribe(); window.removeEventListener('keydown', onKey) })
  return { groups, activeId, active, busy, refresh, perform, toggleSelection, dissolve, afterNodeDrop, openAt, resize,
    graphId: options.graphId, ready: computed(connectionReady) }
}

export type BoardGroups = ReturnType<typeof useBoardGroups>
