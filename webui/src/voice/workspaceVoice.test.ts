import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createRenderer, defineComponent, h, nextTick, onBeforeUnmount, provide, ref } from 'vue'
import WorkspaceVoiceHost from './WorkspaceVoiceHost.vue'
import VoiceCallButton from './VoiceCallButton.vue'
import { createWorkspaceVoice, workspaceVoiceKey } from './workspaceVoice'
import { ConferenceAudio } from './ConferenceAudio'
import { voiceRequest } from '../voiceApi'

const connections = vi.hoisted(() => [] as any[])
vi.mock('../voiceApi', () => ({ voiceRequest: vi.fn(async (_target, _path, options) =>
  JSON.parse(String(options?.body)).action === 'prepare'
    ? { ok: true, annotation_id: 'a'.repeat(32), displays: [{ id: '1', label: 'Monitor', width: 1920, height: 1080, x: 0, y: 0 }] }
    : { ok: true }) }))
vi.mock('../api', () => ({ listMobileNodes: vi.fn(async () => []) }))
vi.mock('./ConferenceAudio', () => ({ ConferenceAudio: vi.fn(class {
  open = vi.fn(async () => {})
  close = vi.fn(async () => {})
  muteMicrophone = vi.fn()
}) }))
vi.mock('../composables/useNodeVoiceCall', async () => {
  const { ref, onBeforeUnmount } = await import('vue')
  return { useNodeVoiceCall: () => {
    const active = ref(false), connected = ref(false)
    const hangup = vi.fn(() => { active.value = false; connected.value = false })
    const call = { active, connected, hangup, start: vi.fn(async () => { active.value = true; connected.value = true }),
      stage: ref('通话中'), error: ref(''),
      contextStatus: ref(''), feedbackStatus: ref(''),
      desktopSession: () => ({ target: { base: '', node: 'Agent', graph: 'graph' }, session: 'voice' }),
      recordSaving: ref(false), recordError: ref(''), userCaption: ref(''), assistantCaption: ref(''), taskStatus: ref('') }
    onBeforeUnmount(hangup)
    connections.push(call)
    return call
  } }
})

// A Vue renderer tests real component lifetimes without browser/media permissions.
type Element = { type: string; children: Element[]; parent: Element | null; props: Record<string, any>; style: Record<string, string>; text: string }
const element = (type: string): Element => ({ type, children: [], parent: null, props: {}, style: {}, text: '' })
const renderer = createRenderer<Element, Element>({
  createElement: element, createText: text => ({ ...element('#text'), text }), createComment: text => ({ ...element('#comment'), text }),
  setText: (node, text) => { node.text = text }, setElementText: (node, text) => { node.text = text; node.children = [] },
  parentNode: node => node.parent,
  nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] || null,
  patchProp: (node, key, _old, value) => { node.props[key] = value },
  insert(node, parent, anchor) {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    parent.children.splice(index < 0 ? parent.children.length : index, 0, node); node.parent = parent
  },
  remove(node) { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = null },
})
const disposers: (() => void)[] = []
beforeEach(() => {
  vi.clearAllMocks(); connections.length = 0
  vi.stubGlobal('AudioContext', class {})
  vi.stubGlobal('RTCPeerConnection', class {})
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn() } })
})
afterEach(() => { disposers.splice(0).forEach(dispose => dispose()); vi.unstubAllGlobals() })
async function flush() { for (let i = 0; i < 5; i++) await nextTick() }

function mountWorkspace() {
  const voice = createWorkspaceVoice(), selected = ref('Agent'), graph = ref('graph'), panel = ref(true), mobile = ref(false)
  const root = element('root')
  const app = renderer.createApp(defineComponent({ setup() {
    provide(workspaceVoiceKey, voice); onBeforeUnmount(voice.stopAll)
    return () => h('main', [panel.value ? h(mobile.value ? 'mobile-chat' : 'desktop-chat', { key: `${graph.value}:${selected.value}:${mobile.value}` }, [
      h(VoiceCallButton, { graphId: graph.value, nodeId: selected.value }),
    ]) : null, h(WorkspaceVoiceHost)])
  } }))
  app.mount(root); disposers.push(() => app.unmount())
  return { voice, selected, graph, panel, mobile, root }
}

it.each([false, true])('has no screen sharing or annotation enable controls on mobile=%s', async isMobile => {
  const { voice, mobile, root } = mountWorkspace()
  mobile.value = isMobile
  voice.start('graph', 'Agent'); await flush()
  const texts = (node: Element): string[] => [node.text, ...node.children.flatMap(texts)]
  const content = texts(root).join(' ')
  for (const label of ['开启桌面标注', '关闭标注', '确认并开启标注', '单独开启', '共享此浏览器屏幕', '共享执行端屏幕', '停止共享', '共享画面预览']) expect(content).not.toContain(label)
  expect(voiceRequest).not.toHaveBeenCalled()
})

it('keeps the exact connection and microphone across desktop close, mobile back, node and graph navigation', async () => {
  const { voice, selected, graph, panel, mobile } = mountWorkspace()
  voice.start('graph', 'Agent'); await flush()
  const call = connections[0], room = voice.sessions[0]!.room, mixer = room.audio.value!
  expect(voice.status('graph', 'Agent')).toBe('connected')
  panel.value = false; await flush()
  mobile.value = true; selected.value = 'Other'; panel.value = true; await flush()
  panel.value = false; graph.value = 'another'; await flush()
  voice.expanded.value = false; await flush()
  voice.expanded.value = true; await flush()
  expect(connections).toHaveLength(1)
  expect(call.hangup).not.toHaveBeenCalled()
  expect(mixer.close).not.toHaveBeenCalled()
  expect(voice.status('graph', 'Agent')).toBe('connected')
  expect(voice.status('another', 'Agent')).toBeNull()
})

it('clicking the connected node button hangs up only that node and clears its badge', async () => {
  const { voice, root } = mountWorkspace()
  voice.start('graph', 'Agent'); await flush()
  voice.sessions[0]!.room.add(['Other']); await flush()
  const chat = root.children[0]!.children.find(node => node.type === 'desktop-chat')!
  chat.children[0]!.props.onClick({ stopPropagation() {} }); await flush()
  expect(connections[0].hangup).toHaveBeenCalledOnce()
  expect(connections[1].hangup).not.toHaveBeenCalled()
  expect(voice.status('graph', 'Agent')).toBeNull()
  expect(voice.status('graph', 'Other')).toBe('connected')
  expect(voice.sessions[0]!.room.audio.value!.close).not.toHaveBeenCalled()
})

it('does not duplicate active participants and keeps different graphs independent', async () => {
  const { voice } = mountWorkspace()
  voice.start('graph', 'Agent'); voice.start('graph', 'Agent'); await flush()
  voice.sessions[0]!.room.add(['Other']); await flush()
  voice.start('graph', 'Other'); await flush()
  expect(voice.sessions).toHaveLength(1)
  voice.start('second', 'Agent'); await flush()
  expect(voice.sessions).toHaveLength(2)
  voice.hangup('graph', 'Agent'); await flush()
  expect(voice.status('second', 'Agent')).toBe('connected')
})

it('cancels pending microphone permission without resurrecting the call', async () => {
  let resolve!: () => void
  vi.mocked(ConferenceAudio).mockImplementationOnce(class {
    open = vi.fn(() => new Promise<void>(done => { resolve = done }))
    close = vi.fn(async () => {})
    muteMicrophone = vi.fn()
  } as unknown as typeof ConferenceAudio)
  const { voice } = mountWorkspace()
  voice.start('graph', 'Agent')
  expect(voice.status('graph', 'Agent')).toBe('connecting')
  voice.hangup('graph', 'Agent'); resolve(); await flush()
  expect(voice.status('graph', 'Agent')).toBeNull()
  expect(connections).toHaveLength(0)
  expect(voice.sessions[0]!.room.audio.value!.close).toHaveBeenCalledOnce()
})

it('clears failed call status and releases calls only when the workspace is unmounted', async () => {
  const { voice, panel } = mountWorkspace()
  voice.start('graph', 'Agent'); voice.start('graph', 'Other'); await flush()
  connections[0].hangup(); await flush()
  expect(voice.status('graph', 'Agent')).toBeNull()
  panel.value = false; await flush()
  expect(connections[1].hangup).not.toHaveBeenCalled()
  disposers.pop()!(); await flush()
  expect(connections[1].hangup).toHaveBeenCalledOnce()
  expect(voice.status('graph', 'Other')).toBeNull()
})

it('never starts capture while idle, navigating or collapsing the call', async () => {
  vi.useFakeTimers()
  const getDisplayMedia = vi.fn()
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(), getDisplayMedia } })
  try {
    const { voice, panel, selected } = mountWorkspace()
    voice.start('graph', 'Agent'); await flush()
    panel.value = false; selected.value = 'Other'; voice.expanded.value = false; await flush()
    await vi.advanceTimersByTimeAsync(60000)
    expect(getDisplayMedia).not.toHaveBeenCalled()
    expect(voiceRequest).not.toHaveBeenCalled()
    expect(connections[0].hangup).not.toHaveBeenCalled()
  } finally { vi.useRealTimers() }
})

it('keeps unsaved transcripts available after navigation and disallows dismiss until saved', async () => {
  const { voice, panel, root } = mountWorkspace()
  voice.start('graph', 'Agent'); await flush()
  connections[0].recordSaving.value = true
  voice.hangup('graph', 'Agent'); panel.value = false; await flush()
  function closeButton(node: Element): Element | undefined {
    if (node.type === 'button' && node.text === '关闭') return node
    for (const child of node.children) { const found = closeButton(child); if (found) return found }
  }
  expect(closeButton(root)!.props.disabled).toBe(true)
  connections[0].recordError.value = '保存失败'; connections[0].recordSaving.value = false; await flush()
  expect(closeButton(root)!.props.disabled).toBe(true)
  connections[0].recordError.value = ''; await flush()
  expect(closeButton(root)!.props.disabled).toBe(false)
  closeButton(root)!.props.onClick(); await flush()
  expect(voice.sessions).toHaveLength(0)
})
