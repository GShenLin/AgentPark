import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRenderer, nextTick } from 'vue'
import * as Vue from 'vue'
import { readFileSync } from 'node:fs'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

const state = vi.hoisted(() => ({
  mounts: 0, unmounts: 0, disconnect: (_message: string) => {},
  restore: vi.fn(async () => {}), activate: vi.fn(), suspend: vi.fn(),
}))
vi.mock('../src/portal/useBoardReconnect', () => ({ useBoardReconnect: vi.fn() }))
vi.mock('../src/portal/workerBridge', () => ({ attachBoardWorker: vi.fn(async () => () => {}) }))
vi.mock('../src/portal/connection', () => ({ connectBoard: vi.fn(async (_id, _stun, disconnected) => {
  state.disconnect = disconnected
  return { rpc: {}, close: vi.fn(), describeTransport: async () => '已通过中继连接' }
}) }))
vi.mock('../src/App.vue', async () => {
  const { defineComponent, h, inject, onBeforeUnmount, ref } = await import('vue')
  const { cloudBoardSession } = await import('../src/portal/boardSession')
  return { __esModule: true, default: defineComponent({ setup() {
    state.mounts += 1
    const draft = ref('')
    const unregister = inject(cloudBoardSession)!.register({ restore: state.restore, activate: state.activate, suspend: state.suspend })
    onBeforeUnmount(() => { state.unmounts += 1; unregister() })
    return () => h('textarea', { value: draft.value, onInput: (value: string) => { draft.value = value } })
  } }) }
})
import PortalRoot from '../src/portal/PortalRoot.vue'
// Vitest loads SFC setup in SSR mode. Compile its real template for the custom
// renderer so lifecycle/identity assertions exercise the production branches.
const { descriptor } = parse(readFileSync(new URL('../src/portal/PortalRoot.vue', import.meta.url), 'utf8'))
const script = compileScript(descriptor, { id: 'retained-board-test' })
const template = compileTemplate({
  source: descriptor.template!.content, filename: 'PortalRoot.vue', id: 'retained-board-test',
  compilerOptions: { mode: 'function', bindingMetadata: script.bindings },
})
const Portal = { ...PortalRoot, render: new Function('Vue', template.code)(Vue) }

interface HostNode extends EventTarget { tag: string; text: string; props: Record<string, unknown>; children: HostNode[]; parent: HostNode | null }
function node(tag: string, text = ''): HostNode { return Object.assign(new EventTarget(), { tag, text, props: {}, children: [], parent: null }) }
const renderer = createRenderer<HostNode, HostNode>({
  createElement: tag => node(tag), createText: text => node('#text', text), createComment: text => node('#comment', text),
  setText: (target, text) => { target.text = text }, setElementText: (target, text) => { target.text = text; target.children = [] },
  parentNode: target => target.parent,
  nextSibling: target => target.parent?.children[target.parent.children.indexOf(target) + 1] || null,
  patchProp: (target, key, _old, value) => { target.props[key] = value },
  insert(target, parent, anchor) {
    if (target.parent) target.parent.children.splice(target.parent.children.indexOf(target), 1)
    target.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(target)
    else parent.children.splice(index, 0, target)
  },
  remove(target) { if (target.parent) target.parent.children.splice(target.parent.children.indexOf(target), 1); target.parent = null },
})
function find(root: HostNode, predicate: (value: HostNode) => boolean): HostNode | undefined {
  if (predicate(root)) return root
  for (const child of root.children) { const result = find(child, predicate); if (result) return result }
}
let unmount: (() => void) | undefined
afterEach(() => { unmount?.(); vi.unstubAllGlobals() })

describe('portal retained Board', () => {
  it('keeps the same mounted chat and unsent draft through disconnect, failed restore and retry', async () => {
    vi.stubGlobal('location', { pathname: `/board/${'a'.repeat(64)}` })
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ devices: [{
      peer_id: 'a'.repeat(64), name: 'Test PC', portal_board: true, stun_urls: [],
    }] }) })))
    const root = node('root')
    const app = renderer.createApp(Portal)
    app.provide(Vue.ssrContextKey, {})
    app.mount(root)
    unmount = () => app.unmount()
    await vi.waitFor(() => expect(state.mounts).toBe(1))
    const input = find(root, item => item.tag === 'textarea')!
    ;(input.props.onInput as (value: string) => void)('尚未发送的输入')
    await nextTick()
    state.disconnect('network unavailable')
    await nextTick()
    expect(find(root, item => item.tag === 'textarea')).toBe(input)
    expect(find(root, item => item.props.class === 'board-content')?.props.inert).toBe(true)
    state.restore.mockRejectedValueOnce(new Error('节点已不存在或不可访问'))
    const retry = () => (find(root, item => item.tag === 'button' && item.text === '重新连接')!.props.onClick as () => Promise<void>)()
    await retry()
    await nextTick()
    expect(state.activate).not.toHaveBeenCalled()
    expect(state.unmounts).toBe(0)
    expect(input.props.value).toBe('尚未发送的输入')
    await retry()
    await nextTick()
    expect(find(root, item => item.props.class === 'board-content')?.props.inert).toBe(false)
    expect(state.activate).toHaveBeenCalledOnce()
    expect(state.mounts).toBe(1)
    expect(state.unmounts).toBe(0)
    expect(input.props.value).toBe('尚未发送的输入')
  })
})
