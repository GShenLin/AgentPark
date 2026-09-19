import { expect, it, vi } from 'vitest'
import { createRenderer, h, nextTick } from 'vue'
import * as Vue from 'vue'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { readFileSync } from 'node:fs'
import type { ProviderInfo } from '../src/api'

vi.mock('../src/components/ProviderSelect.vue', () => ({ default: {
  props: ['modelValue', 'providers', 'optionIds'], emits: ['change'],
  setup: (_: unknown, { emit }: Vue.SetupContext) => () => h('provider-select', { onChange: (v: string) => emit('change', v) }),
} }))
vi.mock('../src/components/FormSelect.vue', () => ({ default: {
  props: ['modelValue'], emits: ['change'],
  setup: (props: { modelValue: string }, { emit, slots, attrs }: Vue.SetupContext) => () => h('select', {
    ...attrs, value: props.modelValue, onChange: (v: string) => emit('change', v),
  }, slots.default?.()),
} }))
vi.mock('../src/components/FormTextInput.vue', () => ({ default: { setup: () => () => h('input') } }))
import Panel from '../src/components/settings/CompanionModelSettings.vue'

const { descriptor } = parse(readFileSync(new URL('../src/components/settings/CompanionModelSettings.vue', import.meta.url), 'utf8'))
Panel.render = new Function('Vue', compile(descriptor.template!.content, {
  mode: 'function', prefixIdentifiers: true, bindingMetadata: compileScript(descriptor, { id: 'companion-model-test' }).bindings,
}).code)(Vue)

type Host = { type: string; text: string; props: Record<string, unknown>; children: Host[]; parent?: Host }
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
const content = (root: Host): string => root.text + root.children.map(content).join('')
const providers: ProviderInfo[] = [
  { id: 'p', models: ['first', 'second'], supportmode: ['chat'] },
  { id: 'q', models: ['other'], supportmode: ['chat'] },
]
function mount(data: Record<string, unknown>) {
  const root = node('root')
  const state = Vue.ref(data)
  const app = renderer.createApp({ setup: () => () => h(Panel, {
    data: state.value, providers, 'onUpdate:data': value => { state.value = value },
  }) })
  app.provide(Vue.ssrContextKey, { modules: new Set() })
  app.mount(root)
  return { root, state, close: () => app.unmount() }
}

it('selects and persists an explicit nondefault Model ID', async () => {
  const { root, state, close } = mount({ provider_id: 'p', model: 'first', tools: ['console_tools'] })
  const model = nodes(root).find(el => el.type === 'select')!
  expect(content(model)).toContain('second')
  ;(model.props.onChange as (v: string) => void)('second')
  await nextTick()
  expect(state.value).toEqual({ provider_id: 'p', model: 'second', tools: ['console_tools'] })
  expect(model.props.value).toBe('second')
  close()
})

it('clears incompatible model on provider change and refreshes available models', async () => {
  const { root, state, close } = mount({ provider_id: 'p', model: 'second' })
  const provider = nodes(root).find(el => el.type === 'provider-select')!
  ;(provider.props.onChange as (v: string) => void)('q')
  await nextTick()
  expect(state.value).toEqual({ provider_id: 'q' })
  const model = nodes(root).find(el => el.type === 'select')!
  expect(content(model)).toContain('other')
  expect(content(model)).not.toContain('second')
  close()
})

it('keeps removed models visible as invalid until the user replaces them', () => {
  const { root, close } = mount({ provider_id: 'p', model: 'removed' })
  expect(content(root)).toContain('removed (unavailable)')
  expect(content(root)).toContain('Select a model allowed by this Provider.')
  close()
})
