import { expect, it, vi } from 'vitest'
import { createRenderer, h } from 'vue'
import * as Vue from 'vue'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { readFileSync } from 'node:fs'
import { withPersistedCapabilityState } from '../src/components/agent-board/capabilitySchemaState'

vi.mock('../src/components/FormCheckbox.vue', () => ({ default: {
  props: ['modelValue', 'disabled'], emits: ['update:modelValue'],
  setup: (props: { disabled: boolean }, { emit }: Vue.SetupContext) => () => h('checkbox', {
    disabled: props.disabled, onChange: () => emit('update:modelValue', true),
  }),
} }))
import Option from '../src/components/agent-board/FieldMultiSelectOption.vue'

const { descriptor } = parse(readFileSync(new URL('../src/components/agent-board/FieldMultiSelectOption.vue', import.meta.url), 'utf8'))
Option.render = new Function('Vue', compile(descriptor.template!.content, {
  mode: 'function', prefixIdentifiers: true, bindingMetadata: compileScript(descriptor, { id: 'plugin-diagnostics-test' }).bindings,
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

it.each(['unavailable', 'error'])('preserves %s diagnostics for selected capabilities', status => {
  const schema = { plugins: { options: [{ value: 'broken', status, diagnostics: ['manifest discovery: invalid JSON'] }] } }
  const result = withPersistedCapabilityState(schema, { plugins: ['broken'] })
  expect(result.plugins.options[0]).toEqual({ ...schema.plugins.options[0], enabled: true })
  expect(schema.plugins.options[0].status).toBe(status)
})

it.each([
  { selected: false, status: 'unavailable', blocked: true },
  { selected: true, status: 'unavailable', blocked: false },
  { selected: false, status: 'available', blocked: false },
  { selected: false, status: 'error', blocked: false },
])('handles selection $selected / $status without hiding diagnostics', ({ selected, status, blocked }) => {
  const root = node('root')
  const toggle = vi.fn()
  const app = renderer.createApp({ setup: () => () => h(Option, {
    option: {
      value: 'broken', title: 'broken', description: '', meta: '', sourceLabel: 'Plugin',
      statusLabel: status, statusClass: '', dependencySummary: '',
      diagnosticLines: ['manifest discovery: plugin.json: invalid JSON'], nextRunLabel: '', status,
    }, selected, diagnosticKeyPrefix: 'plugin', onToggle: toggle,
  }) })
  app.provide(Vue.ssrContextKey, { modules: new Set() })
  app.mount(root)
  try {
    const row = nodes(root).find(el => el.props.role === 'checkbox')!
    const checkbox = nodes(root).find(el => el.type === 'checkbox')!
    expect(row.props['aria-disabled']).toBe(String(blocked))
    expect(checkbox.props.disabled).toBe(blocked)
    expect(content(root)).toContain('manifest discovery: plugin.json: invalid JSON')
    ;(row.props.onClick as () => void)()
    for (const handler of row.props.onKeydown as Array<(event: unknown) => void>) {
      handler({ key: 'Enter', preventDefault() {} })
      handler({ key: ' ', preventDefault() {} })
    }
    ;(checkbox.props.onChange as () => void)()
    expect(toggle).toHaveBeenCalledTimes(blocked ? 0 : 4)
    if (!blocked) expect(toggle).toHaveBeenCalledWith('broken')
  } finally {
    app.unmount()
  }
})
