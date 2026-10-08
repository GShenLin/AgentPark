import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createRenderer, defineComponent, h, nextTick, onBeforeUnmount, provide, ref } from 'vue'
import WorkspaceVoiceHost from './WorkspaceVoiceHost.vue'
import VoiceCallButton from './VoiceCallButton.vue'
import { createWorkspaceVoice, workspaceVoiceKey } from './workspaceVoice'
import { ConferenceAudio } from './ConferenceAudio'

const connections = vi.hoisted(() => [] as any[])
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
      screenSupported: ref(false), screenTransport: ref('frames'), stage: ref('通话中'), error: ref(''),
      screenFrame: vi.fn(() => true), screenStopped: vi.fn(), screenMessageLimit: () => 64000,
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

it('continues screen frames with the chat closed and the controls collapsed, then releases capture on hangup', async () => {
  vi.useFakeTimers()
  const track = { stop: vi.fn(), label: 'Screen', applyConstraints: vi.fn(async () => {}) }
  const stream = { getTracks: () => [track], getVideoTracks: () => [track] }
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(), getDisplayMedia: vi.fn(async () => stream) } })
  vi.stubGlobal('document', { createElement: (kind: string) => kind === 'video'
    ? { play: async () => {}, pause: vi.fn(), readyState: 2, videoWidth: 1920, videoHeight: 1080 }
    : { getContext: () => ({ drawImage: vi.fn() }), toDataURL: () => 'data:image/jpeg;base64,frame' } })
  try {
    const { voice, panel, selected, root } = mountWorkspace()
    voice.start('graph', 'Agent'); await flush()
    connections[0].screenSupported.value = true; await flush()
    function findShare(node: Element): Element | undefined {
      if (node.type === 'button' && node.text === '共享屏幕') return node
      for (const child of node.children) { const found = findShare(child); if (found) return found }
    }
    await findShare(root)!.props.onClick(); await flush()
    expect(connections[0].screenFrame).toHaveBeenCalled()
    panel.value = false; selected.value = 'Other'; voice.expanded.value = false; await flush()
    const before = connections[0].screenFrame.mock.calls.length
    await vi.advanceTimersByTimeAsync(1000)
    expect(connections[0].screenFrame.mock.calls.length).toBeGreaterThan(before)
    expect(track.stop).not.toHaveBeenCalled()
    voice.hangup('graph', 'Agent'); await flush()
    expect(track.stop).toHaveBeenCalledOnce()
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
