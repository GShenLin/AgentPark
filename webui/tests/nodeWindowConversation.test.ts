import { afterEach, expect, test, vi } from 'vitest'
import { createRenderer, defineComponent, h, nextTick, onMounted, onBeforeUnmount, provide, ref } from 'vue'
import NodeCardItem from '../src/components/agent-board/NodeCardItem.vue'
import { AgentBoardKey, type AgentBoardContext, type NodeCard } from '../src/components/agent-board/context'

vi.mock('../src/voice/VoiceCallButton.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/composables/useNodeUnread', () => ({ useNodeUnread: () => ({ receipt: () => '', acknowledge: vi.fn() }) }))
vi.mock('../src/i18n', () => ({ t: (key: string) => key }))
const processApi = vi.hoisted(() => ({ getHarnessProcess: vi.fn(), controlHarnessProcess: vi.fn() }))
vi.mock('../src/harnessApi', () => ({ ...processApi, harnessNodeTypes: new Set(['codex_node']) }))

type Element = { type: string; children: Element[]; parent: Element | null; props: Record<string, any>; text: string }
const element = (type: string): Element => ({ type, children: [], parent: null, props: {}, text: '' })
const renderer = createRenderer<Element, Element>({
  createElement: element, createText: text => ({ ...element('#text'), text }), createComment: () => element('#comment'),
  setText: (node, text) => { node.text = text }, setElementText: (node, text) => { node.text = text; node.children = [] },
  parentNode: node => node.parent, nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] || null,
  patchProp: (node, key, _old, value) => { node.props[key] = value },
  insert(node, parent, anchor) {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    parent.children.splice(index < 0 ? parent.children.length : index, 0, node); node.parent = parent
  },
  remove(node) { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = null },
})
const disposers: (() => void)[] = []
afterEach(() => disposers.splice(0).forEach(dispose => dispose()))
const walk = (node: Element): Element[] => [node, ...node.children.flatMap(walk)]

function mountCard(withConversation = true, typeId = 'text_node', detached = true) {
  const pulse = ref<Record<string, number>>({}), liveReply = ref('正在执行'), draft = ref('未发送的草稿'), mounts = vi.fn(), unmounts = vi.fn()
  const trigger = vi.fn(async () => {}), pause = vi.fn(async () => {}), close = vi.fn(), minimize = vi.fn(), remove = vi.fn(async () => {})
  const openConversation = vi.fn(), pointerDown = vi.fn()
  const context = {
    nodeDonePulse: pulse, currentGraphId: ref('graph'), selectedNodeId: ref('Agent'), renamingNodeId: ref(''),
    nodeConfigs: ref({}), nodeNotes: ref({}), dragHoverTargetId: ref(''), suppressClickUntil: ref(0),
    isClockNode: () => false, isClockRunning: () => false, isNodeRunning: () => false, isNodeStopped: () => false,
    isNodeSelected: () => false, isDragging: () => false, isNodeWorking: () => false, itemStyle: () => ({}),
    previewMessage: (text: string) => text, finishNodeRename: vi.fn(),
    triggerNode: trigger, toggleNodeStop: pause, deleteNodeCard: remove,
    onItemClick: openConversation, onItemPointerDown: pointerDown,
  } as unknown as AgentBoardContext
  const Conversation = defineComponent({ setup() {
    onMounted(mounts); onBeforeUnmount(unmounts)
    return () => h('section', [h('p', liveReply.value), h('textarea', { value: draft.value })])
  } })
  const root = element('root')
  const node = { id: 'Agent', name: 'GPT1', typeId, last_message: '普通画布预览' } as NodeCard
  const app = renderer.createApp({ setup() {
    provide(AgentBoardKey, context)
    return () => h(NodeCardItem, { node, detached, onClose: close, onMinimize: minimize }, withConversation ? { content: () => h(Conversation) } : undefined)
  } })
  app.mount(root); disposers.push(() => app.unmount())
  return { root, pulse, liveReply, draft, mounts, unmounts, trigger, pause, close, minimize, remove, openConversation, pointerDown }
}

function bubble(target: Element, name: 'onClick' | 'onPointerdown') {
  let stopped = false
  const event = { target, stopPropagation: () => { stopped = true } }
  for (let node: Element | null = target; node && !stopped; node = node.parent) node.props[name]?.(event)
}

test('Harness status, error and blank space open the card; process buttons act without opening or dragging', async () => {
  processApi.getHarnessProcess.mockResolvedValue({ state: 'error', error: 'Provider configuration error' })
  processApi.controlHarnessProcess.mockResolvedValue({ state: 'ready', error: '' })
  const c = mountCard(false, 'codex_node', false)
  await nextTick(); await nextTick()
  const controls = walk(c.root).find(node => node.props.class === 'harness-process-controls')!
  const status = walk(controls).find(node => node.props.role === 'status')!
  const error = walk(controls).find(node => node.props.role === 'alert')!
  for (const target of [controls, status, error]) {
    bubble(target, 'onPointerdown'); bubble(target, 'onClick')
  }
  expect(c.openConversation).toHaveBeenCalledTimes(3)
  expect(c.pointerDown).toHaveBeenCalledTimes(3)
  const start = walk(controls).find(node => node.type === 'button')!
  bubble(start, 'onPointerdown'); bubble(start, 'onClick')
  await nextTick(); await nextTick()
  expect(processApi.controlHarnessProcess).toHaveBeenCalledWith('Agent', 'graph', 'start')
  const stop = walk(controls).find(node => node.type === 'button')!
  bubble(stop, 'onPointerdown'); bubble(stop, 'onClick')
  expect(processApi.controlHarnessProcess).toHaveBeenCalledWith('Agent', 'graph', 'stop')
  expect(c.openConversation).toHaveBeenCalledTimes(3)
  expect(c.pointerDown).toHaveBeenCalledTimes(3)
})

test('completion and streamed replies preserve the mounted conversation and draft', async () => {
  const c = mountCard(), originalInput = walk(c.root).find(node => node.type === 'textarea')!
  c.pulse.value = { Agent: 1 }; c.liveReply.value = '执行中第一段回复'
  await nextTick()
  c.pulse.value = { Agent: 2 }; c.liveReply.value += '，继续输出'
  await nextTick()
  expect(c.mounts).toHaveBeenCalledOnce()
  expect(c.unmounts).not.toHaveBeenCalled()
  expect(walk(c.root).find(node => node.type === 'textarea')).toBe(originalInput)
  expect(originalInput.props.value).toBe('未发送的草稿')
  expect(walk(c.root).map(node => node.text).join('')).toContain('执行中第一段回复，继续输出')
  expect(walk(c.root).some(node => node.props.class === 'node-body')).toBe(false)
  expect(walk(c.root).some(node => node.props.class === 'node-add-output')).toBe(false)
})

test('the original title and Trigger, Pause, close actions remain available', () => {
  const c = mountCard(), nodes = walk(c.root), event = { stopPropagation() {} }
  expect(nodes.find(node => node.props.class === 'node-title')?.text).toBe('GPT1')
  nodes.find(node => node.props.class === 'node-trigger')!.props.onClick(event)
  nodes.find(node => node.props.class === 'node-pause')!.props.onClick(event)
  nodes.find(node => node.props['aria-label'] === '关闭小 Agent')!.props.onClick(event)
  expect(c.trigger).toHaveBeenCalledExactlyOnceWith('Agent')
  expect(c.pause).toHaveBeenCalledExactlyOnceWith('Agent')
  expect(c.close).toHaveBeenCalledOnce()
  expect(c.remove).not.toHaveBeenCalled()
})

test('cards without the conversation slot retain their existing preview and output button', () => {
  const nodes = walk(mountCard(false).root)
  expect(nodes.map(node => node.text).join('')).toContain('普通画布预览')
  expect(nodes.some(node => node.props.class === 'node-add-output')).toBe(true)
})

test('minimize emits only the window action and retains the composer', () => {
  const c = mountCard(), input = walk(c.root).find(node => node.type === 'textarea')
  walk(c.root).find(node => node.props['aria-label'] === '最小化小 Agent')!.props.onClick({ stopPropagation() {} })
  expect(c.minimize).toHaveBeenCalledOnce()
  expect(c.close).not.toHaveBeenCalled()
  expect(c.pause).not.toHaveBeenCalled()
  expect(c.unmounts).not.toHaveBeenCalled()
  expect(walk(c.root).find(node => node.type === 'textarea')).toBe(input)
})
