import { expect, it, vi } from 'vitest'
import { createRenderer, h, nextTick } from 'vue'
import * as Vue from 'vue'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { readFileSync } from 'node:fs'
vi.mock('../src/components/settings/AgentInferenceProfileSelect.vue', () => ({ default: {
  props: ['modelValue'], emits: ['update:modelValue'],
  setup: (props: { modelValue: string }, { emit }: Vue.SetupContext) => () => h('preset-select', {
    value: props.modelValue, onChange: (v: string) => emit('update:modelValue', v),
  }),
} }))
vi.mock('../src/components/FormTextInput.vue', () => ({ default: {
  props: ['modelValue'], emits: ['update:modelValue'],
  setup: (props: { modelValue: string }, { emit }: Vue.SetupContext) => () => h('input', {
    value: props.modelValue, onChange: (v: string) => emit('update:modelValue', v),
  }),
} }))
import Panel from '../src/components/settings/CompanionSettingsForm.vue'

const { descriptor } = parse(readFileSync(new URL('../src/components/settings/CompanionSettingsForm.vue', import.meta.url), 'utf8'))
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
function mount(data: Record<string, unknown>) {
  const root = node('root')
  const state = Vue.ref(data)
  const app = renderer.createApp({ setup: () => () => h(Panel, {
    data: state.value, 'onUpdate:data': value => { state.value = value },
  }) })
  app.provide(Vue.ssrContextKey, { modules: new Set() })
  app.mount(root)
  return { root, state, close: () => app.unmount() }
}

it('selects one Preset and preserves local node settings', async () => {
  const data = { profile_id: 'Companion', working_path: 'D:/work', node_id: 'Companion' }
  const { root, state, close } = mount(data)
  const select = nodes(root).find(el => el.type === 'preset-select')!
  expect(select.props.value).toBe('Companion')
  ;(select.props.onChange as (v: string) => void)('GPT')
  await nextTick()
  expect(state.value).toEqual({ ...data, profile_id: 'GPT' })
  expect(select.props.value).toBe('GPT')
  expect(content(root)).not.toContain('Provider ID')
  expect(content(root)).toContain('Node Preset Editor')
  close()
})

it('changes the working directory without copying model fields into Companion settings', async () => {
  const { root, state, close } = mount({ profile_id: 'Companion', working_path: 'D:/old' })
  const input = nodes(root).find(el => el.type === 'input')!
  ;(input.props.onChange as (v: string) => void)('D:/new')
  await nextTick()
  expect(state.value).toEqual({ profile_id: 'Companion', working_path: 'D:/new' })
  close()
})
