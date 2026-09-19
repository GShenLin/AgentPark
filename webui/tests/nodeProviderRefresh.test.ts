import { readFileSync } from 'node:fs'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as Vue from 'vue'
import { createRenderer, h, nextTick, ref } from 'vue'
import type { ProviderInfo } from '../src/api'
import { AgentBoardKey, type AgentBoardContext } from '../src/components/agent-board/context'
import { HARNESS_NODE_TYPES } from '../src/composables/useAgentNodeCreateSchema'

const api = vi.hoisted(() => ({ getNodeTemplate: vi.fn() }))
vi.mock('../src/api', () => api)
vi.mock('../src/i18n', () => ({ t: (key: string) => key }))
vi.mock('../src/selectionRequestPolicy', () => ({ waitForSelectionRequestWindow: async () => true }))
vi.mock('../src/components/ProviderSelect.vue', () => ({
  default: { setup: (_: unknown, { attrs }: Vue.SetupContext) => () => h('provider-picker', attrs) },
}))
vi.mock('../src/components/agent-board/NodeNoteField.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/components/ExpandableTextarea.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/components/agent-board/NodeProfileLoadControl.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/components/agent-board/NodeRuntimeEventsFieldGroup.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/mobile/MobileNodeProfilePickerSheet.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/components/ActionButton.vue', () => ({
  default: { setup: (_: unknown, { attrs, slots }: Vue.SetupContext) => () => h('button', attrs, slots.default?.()) },
}))

import Section from '../src/components/agent-board/NodeConfigSection.vue'
import MobileDialog from '../src/mobile/MobileNodeConfigDialog.vue'
import Fields from '../src/components/agent-board/NodeConfigFields.vue'
import FormSelect from '../src/components/FormSelect.vue'

// Use the client templates with a Vue test host, without synthesizing a blur
// or reopening the editor. Vitest otherwise loads the SSR templates.
for (const [component, path] of [
  [Section, '../src/components/agent-board/NodeConfigSection.vue'],
  [MobileDialog, '../src/mobile/MobileNodeConfigDialog.vue'],
  [Fields, '../src/components/agent-board/NodeConfigFields.vue'],
  [FormSelect, '../src/components/FormSelect.vue'],
] as const) {
  const { descriptor } = parse(readFileSync(new URL(path, import.meta.url), 'utf8'))
  component.render = new Function('Vue', compile(descriptor.template!.content, {
    mode: 'function', prefixIdentifiers: true,
    bindingMetadata: compileScript(descriptor, { id: path }).bindings,
  }).code)(Vue)
}

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
async function settle() { for (let i = 0; i < 12; i++) await nextTick() }
function template(providerId: string) {
  return {
    fields: { provider_id: providerId, model: `${providerId}-1` },
    schema: {
      provider_id: { type: 'select' },
      model: { type: 'select', options: [`${providerId}-1`, `${providerId}-2`] },
      reasoning_effort: { type: 'select', options: providerId === 'second' ? ['high', 'max'] : ['low', 'medium'] },
    },
  }
}
const providers: ProviderInfo[] = ['first', 'second', 'third'].map(id => ({
  id, type: 'openai', supportmode: ['chat'], model: `${id}-1`, models: [`${id}-1`, `${id}-2`],
  features: { reasoning_effort: { supported: true, values: id === 'second' ? ['high', 'max'] : ['low', 'medium'] } },
}))
let unmount: (() => void) | undefined
beforeEach(() => {
  vi.resetAllMocks()
  api.getNodeTemplate.mockImplementation(async (_typeId, { providerId }) => template(providerId))
})
afterEach(() => unmount?.())

async function mount(typeId: string, mobile = false) {
  const root = node('root')
  const persist = vi.fn(async () => undefined)
  const errors = vi.fn()
  const app = renderer.createApp(mobile ? MobileDialog : Section, mobile ? {
    open: true, node: { id: 'test-node', type_id: typeId },
    config: { node_id: 'test-node', provider_id: 'first', model: 'first-2', reasoning_effort: 'medium' },
    providers, availableTools: [], agentProfiles: [], graphId: 'default', nodes: [], outputRoutes: [],
    saveFields: persist, saveNote: vi.fn(), renameNode: vi.fn(), saveProfile: vi.fn(),
    loadProfile: vi.fn(), addOutputRoute: vi.fn(), updateOutputRoute: vi.fn(), removeOutputRoute: vi.fn(),
    onError: errors,
  } : {
    node: { id: 'test-node', typeId },
    config: { node_id: 'test-node', provider_id: 'first', model: 'first-2', reasoning_effort: 'medium' },
    providers, availableTools: [], onError: errors,
  })
  app.provide(Vue.ssrContextKey, { modules: new Set() })
  app.provide(AgentBoardKey, {
    currentGraphId: ref('default'), nodeNotes: ref({}),
    refreshNodeConfig: vi.fn(async () => undefined), setNodeFields: persist,
  } as unknown as AgentBoardContext)
  app.mount(root)
  unmount = () => app.unmount()
  await settle()
  const choose = async (providerId: string) => {
    nodes(root).find(el => el.type === 'provider-picker')!.props.onChange(providerId)
    await settle()
  }
  const model = () => nodes(root).find(el => el.type === 'select' && nodes(el).some(child => (
    child.type === 'option' && String(child.props.value).endsWith('-1')
  )))!
  const modelOptions = () => nodes(model()).filter(el => el.type === 'option').map(el => el.props.value)
  const save = async () => {
    const button = nodes(root).find(el => el.type === 'button' && el.props.onClick &&
      nodes(el).some(child => /保存修改|Save Changes|保存配置|保存/.test(child.text)))!
    button.props.onClick()
    await settle()
  }
  const effort = () => nodes(root).find(el => el.type === 'select' && nodes(el).some(child => (
    child.type === 'option' && ['low', 'high'].includes(child.props.value)
  )))!
  return { choose, model, modelOptions, persist, errors, save, effort }
}

describe('provider-dependent node editor models', () => {
  it.each(['agent_node', ...HARNESS_NODE_TYPES])('%s refreshes model value and options after selecting a provider', async typeId => {
    const editor = await mount(typeId)
    expect(editor.model().props.value).toBe('first-2')
    expect(editor.modelOptions()).toEqual(['first-1', 'first-2'])

    await editor.choose('second')

    expect(api.getNodeTemplate).toHaveBeenLastCalledWith(typeId, { providerId: 'second' }, { signal: undefined })
    expect(editor.model().props.value).toBe('second-1')
    expect(editor.modelOptions()).toEqual(['second-1', 'second-2'])
    expect(editor.persist).toHaveBeenCalledWith('test-node', expect.objectContaining({ provider_id: 'second', model: 'second-1' }))
    expect(editor.errors.mock.calls.flat().filter(Boolean)).toEqual([])
  })

  it('keeps the latest provider models when earlier template requests finish last', async () => {
    const editor = await mount('codex_node')
    let resolveSecond!: (value: ReturnType<typeof template>) => void
    api.getNodeTemplate.mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve }))
    await editor.choose('second')
    await editor.choose('third')
    expect(editor.modelOptions()).toEqual(['third-1', 'third-2'])

    resolveSecond(template('second'))
    await settle()
    expect(editor.model().props.value).toBe('third-1')
    expect(editor.modelOptions()).toEqual(['third-1', 'third-2'])
  })
})

describe('mobile provider-dependent models', () => {
  it.each(['hermes_agent_node', 'openclaw_node'])('updates %s reasoning selection and saves the supported provider value', async typeId => {
    const editor = await mount(typeId, true)
    await editor.choose('second')
    expect(editor.effort().props.value).toBe('high')
    expect(nodes(editor.effort()).filter(el => el.type === 'option').map(el => el.props.value)).toEqual(['high', 'max'])
    await editor.save()
    expect(editor.persist).toHaveBeenCalledWith(expect.objectContaining({ reasoning_effort: 'high' }))
  })
  it.each(['agent_node', ...HARNESS_NODE_TYPES])('%s changes the model and list before saving', async typeId => {
    const editor = await mount(typeId, true)
    expect(editor.model().props.value).toBe('first-2')
    await editor.choose('second')
    expect(editor.model().props.value).toBe('second-1')
    expect(editor.modelOptions()).toEqual(['second-1', 'second-2'])
    expect(editor.errors).not.toHaveBeenCalled()
    await editor.save()
    expect(editor.persist).toHaveBeenCalledWith(expect.objectContaining({ provider_id: 'second', model: 'second-1' }))
  })

  it.each(['third', 'first'])('supersedes a pending request when switching to %s', async latest => {
    const editor = await mount('hermes_agent_node', true)
    let resolveSecond!: (value: ReturnType<typeof template>) => void
    api.getNodeTemplate.mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve }))
    await editor.choose('second')
    await editor.save()
    expect(editor.persist).not.toHaveBeenCalled()
    await editor.choose(latest)
    expect(editor.modelOptions()).toEqual([`${latest}-1`, `${latest}-2`])
    resolveSecond(template('second'))
    await settle()
    expect(editor.model().props.value).toBe(`${latest}-1`)
    expect(editor.modelOptions()).toEqual([`${latest}-1`, `${latest}-2`])
    await editor.save()
    expect(editor.persist).toHaveBeenCalledWith(expect.objectContaining({ provider_id: latest, model: `${latest}-1` }))
  })
})
