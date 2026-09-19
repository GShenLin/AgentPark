import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'

const hooks = vi.hoisted(() => ({ unmount: [] as (() => void)[] }))
const api = vi.hoisted(() => ({
  listMobilePcs: vi.fn(), listMobileGraphs: vi.fn(), listGraphProfiles: vi.fn(),
  listMobileNodes: vi.fn(), loadGraph: vi.fn(), getMobileNodeConversation: vi.fn(),
  listProviders: vi.fn(), listTools: vi.fn(), listNodes: vi.fn(), listCliSessions: vi.fn(),
}))
vi.mock('../src/api', async original => ({ ...await original<typeof import('../src/api')>(), ...api }))
vi.mock('vue', async original => ({
  ...await original<typeof import('vue')>(), onBeforeUnmount: (fn: () => void) => hooks.unmount.push(fn),
}))
vi.mock('../src/composables/useGlobalState', () => ({ useGlobalState: () => ({ nodeTriggerInputs: ref({}) }) }))

import { useMobileWorkspace } from '../src/mobile/useMobileWorkspace'
import { useMobileBoardLocation } from '../src/mobile/useMobileBoardLocation'

const scopes: ReturnType<typeof effectScope>[] = []
const deviceUrl = `https://cloud.example/board/${'a'.repeat(64)}`
function mount() {
  const scope = effectScope()
  scopes.push(scope)
  return scope.run(() => {
    const workspace = useMobileWorkspace({ initialPcId: 'local' })
    return { workspace, location: useMobileBoardLocation(workspace, true) }
  })!
}
function unmount() {
  hooks.unmount.splice(0).forEach(fn => fn())
  scopes.splice(0).forEach(scope => scope.stop())
}
beforeEach(() => {
  vi.clearAllMocks()
  const location = { href: deviceUrl }
  vi.stubGlobal('window', {
    location, history: { state: { existing: true }, replaceState: vi.fn((_state, _unused, url) => { location.href = String(url) }) },
  })
  api.listMobilePcs.mockResolvedValue([{ id: 'local', name: 'Device' }])
  api.listMobileGraphs.mockResolvedValue([{ id: 'runtime', graphs: [{ id: 'graph / 中文', name: 'Graph' }] }])
  api.listGraphProfiles.mockResolvedValue([])
  api.listMobileNodes.mockResolvedValue([{ id: 'node / 中文', name: 'Node', node_event_seq: 0 }])
  api.loadGraph.mockResolvedValue({ nodes: [], output_routes: {} })
  api.getMobileNodeConversation.mockResolvedValue({ messages: [], live_version: 1 })
  api.listProviders.mockResolvedValue([])
  api.listTools.mockResolvedValue([])
  api.listNodes.mockResolvedValue([])
  api.listCliSessions.mockResolvedValue({ supported: false })
})
afterEach(() => { unmount(); vi.unstubAllGlobals() })

async function openNode() {
  const mounted = mount()
  await mounted.location.initialize()
  await mounted.workspace.selectGraph(mounted.workspace.flatGraphs.value[0]!)
  expect(mounted.workspace.error.value).toBe('')
  await mounted.workspace.selectNode(mounted.workspace.nodes.value[0]!)
  await nextTick()
  return mounted
}

describe('cloud mobile Board location', () => {
  it('restores the exact graph and node with fresh messages after the Board is destroyed', async () => {
    await openNode()
    const saved = window.location.href
    expect(new URL(saved).searchParams.get('mobile_node')).toBe('node / 中文')
    unmount()
    api.getMobileNodeConversation.mockResolvedValue({ messages: [{ id: 'new-message' }], live_version: 2 })
    const next = mount()
    await next.location.initialize()
    expect(next.workspace.view.value).toBe('chat')
    expect(next.workspace.selectedGraph.value?.id).toBe('graph / 中文')
    expect(next.workspace.selectedNode.value?.id).toBe('node / 中文')
    expect(next.workspace.conversation.value?.messages[0]?.id).toBe('new-message')
    expect(window.location.href).toBe(saved)
  })

  it('records back navigation so reconnecting does not reopen the previous node', async () => {
    const current = await openNode()
    current.workspace.backToNodes()
    await nextTick()
    expect(new URL(window.location.href).searchParams.has('mobile_node')).toBe(false)
    unmount()
    const next = mount()
    await next.location.initialize()
    expect(next.workspace.view.value).toBe('nodes')
    next.workspace.backToGraphs()
    await nextTick()
    expect(window.location.href).toBe(deviceUrl)
  })

  it('keeps the original destination when restoration fails and is unmounted again', async () => {
    await openNode()
    unmount()
    const saved = window.location.href
    api.listMobileNodes.mockRejectedValueOnce(new Error('Connection lost'))
    const next = mount()
    await next.location.initialize()
    expect(next.workspace.error.value).toBe('Connection lost')
    unmount()
    expect(window.location.href).toBe(saved)
    const retry = mount()
    await retry.location.initialize()
    expect(retry.workspace.view.value).toBe('chat')
  })

  it.each(['graph', 'node'])('reports a missing %s without choosing another destination', async missing => {
    await openNode()
    unmount()
    if (missing === 'graph') api.listMobileGraphs.mockResolvedValue([{ id: 'runtime', graphs: [] }])
    else api.listMobileNodes.mockResolvedValue([])
    const next = mount()
    await next.location.initialize()
    expect(next.workspace.error.value).toContain('不存在或不可访问')
    expect(next.workspace.selectedNode.value).toBeNull()
  })

  it('does not carry a position over to another device URL', async () => {
    await openNode()
    unmount()
    window.location.href = `https://cloud.example/board/${'b'.repeat(64)}`
    const next = mount()
    await next.location.initialize()
    expect(next.workspace.view.value).toBe('graphs')
  })

  it('does not continue restoring a node after unmount during the initial request', async () => {
    await openNode()
    unmount()
    const saved = window.location.href
    let finish!: (value: unknown) => void
    api.listMobilePcs.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const next = mount()
    const loading = next.location.initialize()
    unmount()
    api.getMobileNodeConversation.mockClear()
    finish([{ id: 'local', name: 'Device' }])
    await loading
    expect(api.getMobileNodeConversation).not.toHaveBeenCalled()
    expect(window.location.href).toBe(saved)
  })
})
