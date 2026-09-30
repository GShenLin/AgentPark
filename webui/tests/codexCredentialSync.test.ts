import { readFileSync } from 'node:fs'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as Vue from 'vue'
import { createRenderer, h, nextTick, reactive } from 'vue'

const api = vi.hoisted(() => ({ syncLocalCodexCredentials: vi.fn() }))
vi.mock('../src/codexCredentialSyncApi', () => api)
vi.mock('../src/settingsApi', () => ({
  activateProviderAccount: vi.fn(), addProviderApiKeyAccount: vi.fn(), deleteProviderAccount: vi.fn(),
}))
vi.mock('../src/components/ActionButton.vue', () => ({
  default: { setup: (_: unknown, { attrs, slots }: Vue.SetupContext) => () => h('button', attrs, slots.default?.()) },
}))
vi.mock('../src/components/DangerButton.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/components/FormTextInput.vue', () => ({ default: { render: () => null } }))
import Control from '../src/components/settings/ProviderOfficialAuthControl.vue'

const { descriptor } = parse(readFileSync(new URL('../src/components/settings/ProviderOfficialAuthControl.vue', import.meta.url), 'utf8'))
Control.render = new Function('Vue', compile(descriptor.template!.content, {
  mode: 'function', prefixIdentifiers: true,
  bindingMetadata: compileScript(descriptor, { id: 'auth-control' }).bindings,
}).code)(Vue)

type Host = { type: string; text: string; props: Record<string, any>; children: Host[]; parent?: Host }
const node = (type: string, text = ''): Host => ({ type, text, props: {}, children: [] })
const renderer = createRenderer<Host, Host>({
  createElement: type => node(type), createText: text => node('text', text), createComment: () => node('comment'),
  setText: (el, text) => { el.text = text }, setElementText: (el, text) => { el.text = text; el.children = [] },
  patchProp: (el, key, _prev, next) => { el.props[key] = next },
  insert(child, parent, anchor) {
    if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    parent.children.splice(index < 0 ? parent.children.length : index, 0, child)
    child.parent = parent
  },
  remove(child) { child.parent?.children.splice(child.parent.children.indexOf(child), 1) },
  parentNode: el => el.parent || null,
  nextSibling: el => el.parent?.children[el.parent.children.indexOf(el) + 1] || null,
})
const nodes = (root: Host): Host[] => [root, ...root.children.flatMap(nodes)]
const text = (root: Host): string => root.text + root.children.map(text).join('')
const syncButton = (root: Host) => nodes(root).find(n => n.type === 'button' && text(n).includes('同步本机 Codex 凭据'))
async function settle() { for (let i = 0; i < 8; i++) await nextTick() }

function mount(overrides: Record<string, unknown> = {}) {
  const props = reactive({
    enabled: true, showToggle: false, showStatus: true, oauthEnabled: true, oauthSupported: true,
    providerAuthId: 'openai', selectedAccountId: '111111111111', busy: false,
    status: { authorized: true, activeAccountId: '222222222222', accounts: [] }, error: '',
    ...overrides,
  })
  const onStatus = vi.fn()
  const onAccount = vi.fn()
  const root = node('root')
  const app = renderer.createApp({ render: () => h(Control, { ...props, onStatus, onAccount } as any) })
  app.provide(Vue.ssrContextKey, {})
  app.mount(root)
  return { root, props, onStatus, onAccount, app }
}

beforeEach(() => vi.clearAllMocks())

describe('local Codex credential sync', () => {
  it('syncs the pinned account, updates status and preserves selection', async () => {
    const view = mount()
    const next = { accountId: '111111111111', sourcePath: '/server/.codex/auth.json', status: { authorized: true } }
    api.syncLocalCodexCredentials.mockResolvedValue(next)
    await syncButton(view.root)!.props.onClick()
    await settle()
    expect(api.syncLocalCodexCredentials).toHaveBeenCalledWith('111111111111')
    expect(view.onStatus).toHaveBeenCalledWith(next.status)
    expect(view.onAccount).not.toHaveBeenCalled()
    expect(text(view.root)).toContain('单次同步')
    expect(text(view.root)).toContain('/server/.codex/auth.json')
    view.app.unmount()
  })

  it('shows the actual sync failure even if an old status error exists', async () => {
    const view = mount({ error: 'previous refresh failure' })
    api.syncLocalCodexCredentials.mockRejectedValue(new Error('本机 Codex 登录账号与当前 AgentPark 账号不一致'))
    await syncButton(view.root)!.props.onClick()
    await settle()
    expect(text(view.root)).toContain('账号不一致')
    expect(view.onStatus).not.toHaveBeenCalled()
    expect(view.onAccount).not.toHaveBeenCalled()
    view.app.unmount()
  })

  it('ignores results after the user switches accounts and prevents duplicate clicks', async () => {
    const view = mount()
    let finish!: (value: unknown) => void
    api.syncLocalCodexCredentials.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const pending = syncButton(view.root)!.props.onClick()
    await syncButton(view.root)!.props.onClick()
    expect(api.syncLocalCodexCredentials).toHaveBeenCalledTimes(1)
    view.props.selectedAccountId = '333333333333'
    finish({ accountId: '111111111111', sourcePath: '/old', status: {} })
    await pending
    await settle()
    expect(view.onStatus).not.toHaveBeenCalled()
    expect(text(view.root)).not.toContain('已读取')
    view.app.unmount()
  })

  it.each([{ providerAuthId: 'anthropic' }, { oauthEnabled: false }])('is only offered for OpenAI OAuth: %j', overrides => {
    const view = mount(overrides)
    expect(syncButton(view.root)).toBeUndefined()
    view.app.unmount()
  })
})
