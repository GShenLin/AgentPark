import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createRenderer, h, nextTick } from 'vue'
import * as Vue from 'vue'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { readFileSync } from 'node:fs'
import type { HarnessInfo } from '../src/harnessApi'

const api = vi.hoisted(() => ({
  listHarnesses: vi.fn(), checkHarness: vi.fn(), operateHarness: vi.fn(), getHarnessJob: vi.fn(),
  listHarnessProcesses: vi.fn(), controlHarnessProcess: vi.fn(),
}))
vi.mock('../src/harnessApi', () => api)
vi.mock('../src/i18n', () => ({ t: (key: string) => key }))
vi.mock('../src/components/ActionButton.vue', () => ({
  default: { setup: (_: unknown, { attrs, slots }: Vue.SetupContext) => () => h('button', attrs, slots.default?.()) },
}))
import Panel from '../src/components/settings/HarnessSettingsPanel.vue'
import Processes from '../src/components/settings/HarnessProcesses.vue'

const { descriptor } = parse(readFileSync(new URL('../src/components/settings/HarnessSettingsPanel.vue', import.meta.url), 'utf8'))
Panel.render = new Function('Vue', compile(descriptor.template!.content, {
  mode: 'function', prefixIdentifiers: true, bindingMetadata: compileScript(descriptor, { id: 'harness-test' }).bindings,
}).code)(Vue)
const processDescriptor = parse(readFileSync(new URL('../src/components/settings/HarnessProcesses.vue', import.meta.url), 'utf8')).descriptor
Processes.render = new Function('Vue', compile(processDescriptor.template!.content, {
  mode: 'function', prefixIdentifiers: true, bindingMetadata: compileScript(processDescriptor, { id: 'process-test' }).bindings,
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
const button = (root: Host, label: string) => nodes(root).find(el => el.type === 'button' && content(el) === `harness.${label}`)
async function settle() { for (let i = 0; i < 10; i++) await nextTick() }
async function click(root: Host, label: string) {
  const el = button(root, label)!
  expect(el).toBeDefined()
  expect(el.props.disabled).toBeFalsy()
  await (el.props.onClick as () => Promise<void>)()
  await settle()
}
function info(overrides: Partial<HarnessInfo> = {}): HarnessInfo {
  return { id: 'pi', name: 'Pi', node_type: 'pi_node', package: '@earendil-works/pi-coding-agent', executable: 'pi',
    transport: 'json-stream', homepage: 'https://example.com', session_support: 'persistent', installation: 'npm',
    status: 'ready', source: 'managed', version: '1.0.0', installed_version: '1.0.0', latest_version: '1.1.0',
    update_status: 'available', update_error: '', executable_path: '/workspace/pi', error: '', can_uninstall: true,
    can_upgrade: true, upgrade_error: '',
    ...overrides }
}
let unmount: (() => void) | undefined
async function mount(value: HarnessInfo, onOpenNode = vi.fn()) {
  api.listHarnesses.mockResolvedValue({ harnesses: [value], jobs: [] })
  const root = node('root')
  const app = renderer.createApp(Panel, { onOpenNode })
  app.provide(Vue.ssrContextKey, { modules: new Set() })
  app.mount(root)
  unmount = () => app.unmount()
  await settle()
  return root
}
beforeEach(() => { vi.resetAllMocks(); vi.useFakeTimers(); api.listHarnessProcesses.mockResolvedValue({ processes: [] }) })
afterEach(() => { unmount?.(); vi.useRealTimers() })

it('offers upgrade after check, disables concurrent actions, and refreshes after completion', async () => {
  const root = await mount(info({ update_status: 'current', latest_version: '1.0.0' }))
  expect(button(root, 'upgrade')).toBeUndefined()
  api.checkHarness.mockResolvedValueOnce(info())
  await click(root, 'check')
  expect(button(root, 'upgrade')).toBeDefined()
  expect(content(root)).toContain('1.1.0')
  const job = { id: 'job', harness_id: 'pi', action: 'upgrade', status: 'running', error: '', output: '' }
  api.operateHarness.mockResolvedValue(job)
  await click(root, 'upgrade')
  expect(api.operateHarness).toHaveBeenCalledWith('pi', 'upgrade')
  expect(button(root, 'upgrade')!.props.disabled).toBe(true)
  expect(button(root, 'uninstall')!.props.disabled).toBe(true)
  api.getHarnessJob.mockResolvedValue({ ...job, status: 'completed', output: 'upgraded' })
  api.checkHarness.mockResolvedValue(info({ version: '1.1.0', installed_version: '1.1.0', update_status: 'current' }))
  await vi.advanceTimersByTimeAsync(1500)
  await settle()
  expect(button(root, 'upgrade')).toBeUndefined()
  expect(button(root, 'reinstall')).toBeDefined()
  expect(content(root)).toContain('harness.upToDate')
  expect(content(root)).toContain('harness.completed')
})

it('upgrades external installations directly with the same upgrade action', async () => {
  const root = await mount(info({ source: 'external', can_uninstall: false }))
  expect(button(root, 'upgrade')).toBeDefined()
  expect(button(root, 'install')).toBeUndefined()
  expect(button(root, 'uninstall')!.props.disabled).toBe(true)
  api.operateHarness.mockResolvedValue({ id: 'job', harness_id: 'pi', action: 'upgrade', status: 'running' })
  await click(root, 'upgrade')
  expect(api.operateHarness).toHaveBeenCalledWith('pi', 'upgrade')
})

it('does not offer a workspace copy for current external installations', async () => {
  const root = await mount(info({ source: 'external', update_status: 'current', can_uninstall: false }))
  expect(button(root, 'install')).toBeUndefined()
  expect(button(root, 'reinstall')).toBeUndefined()
  expect(button(root, 'upgrade')).toBeUndefined()
})

it('reports unsupported installers and disables in-place upgrade', async () => {
  const root = await mount(info({ source: 'external', can_upgrade: false, upgrade_error: 'Use original installer' }))
  expect(button(root, 'upgrade')!.props.disabled).toBe(true)
  expect(content(root)).toContain('Use original installer')
  expect(button(root, 'install')).toBeUndefined()
})

it('shows the detected Termux distribution and its own release status', async () => {
  const root = await mount(info({ id: 'codex', name: 'Codex', source: 'external',
    package: '@mmmbuto/codex-cli-termux', version: 'codex-cli 0.153.3',
    installed_version: '0.153.3', latest_version: '0.153.3', update_status: 'current' }))
  expect(content(root)).toContain('@mmmbuto/codex-cli-termux')
  expect(content(root)).toContain('harness.upToDate')
  expect(button(root, 'upgrade')).toBeUndefined()
})

it('shows registry errors without claiming the installed runtime failed', async () => {
  const root = await mount(info({ latest_version: '', update_status: 'error', update_error: 'registry offline' }))
  expect(button(root, 'upgrade')).toBeUndefined()
  expect(content(root)).toContain('harness.status.ready')
  expect(content(root)).toContain('registry offline')
  expect(content(root)).not.toContain('harness.upToDate')
  expect(button(root, 'check')!.props.disabled).toBeFalsy()
})

it('surfaces a failed upgrade and allows retry after polling', async () => {
  const root = await mount(info())
  api.operateHarness.mockResolvedValue({ id: 'job', harness_id: 'pi', action: 'upgrade', status: 'running' })
  await click(root, 'upgrade')
  api.getHarnessJob.mockResolvedValue({ id: 'job', harness_id: 'pi', action: 'upgrade', status: 'failed', error: 'EBADENGINE' })
  api.checkHarness.mockResolvedValue(info())
  await vi.advanceTimersByTimeAsync(1500)
  await settle()
  expect(content(root)).toContain('EBADENGINE')
  expect(button(root, 'upgrade')!.props.disabled).toBeFalsy()
  expect(content(root)).not.toContain('harness.completed')
})

it('opens the exact graph/node without stopping its process', async () => {
  api.listHarnessProcesses.mockResolvedValue({ processes: [{ harness_id: 'pi', graph_id: 'other-graph', node_id: 'Pi worker', state: 'ready', error: '' }] })
  const openNode = vi.fn()
  const root = await mount(info(), openNode)
  await click(root, 'process.openNode')
  expect(openNode).toHaveBeenCalledExactlyOnceWith({ graphId: 'other-graph', nodeId: 'Pi worker' })
  expect(api.controlHarnessProcess).not.toHaveBeenCalled()
})

it('lists the processes of its Harness and stops the selected graph/node', async () => {
  api.listHarnessProcesses.mockResolvedValue({ processes: [{ harness_id: 'pi', graph_id: 'other-graph', node_id: 'Pi worker', state: 'ready', error: '' }] })
  const root = await mount(info())
  expect(api.listHarnessProcesses).toHaveBeenCalledWith('pi')
  expect(content(root)).toContain('Pi worker')
  expect(content(root)).toContain('other-graph')
  api.controlHarnessProcess.mockResolvedValue({ state: 'stopped', error: '' })
  await click(root, 'process.stop')
  expect(api.controlHarnessProcess).toHaveBeenCalledWith('Pi worker', 'other-graph', 'stop')
  expect(content(root)).not.toContain('Pi worker')
})

it('reports restoration failures separately from a completed installation', async () => {
  const root = await mount(info())
  api.operateHarness.mockResolvedValue({ id: 'job', harness_id: 'pi', action: 'upgrade', status: 'running' })
  await click(root, 'upgrade')
  api.getHarnessJob.mockResolvedValue({ id: 'job', harness_id: 'pi', action: 'upgrade', status: 'completed',
    restore_errors: [{ node_id: 'Pi worker', error: 'Native initialization failed' }] })
  api.checkHarness.mockResolvedValue(info({ update_status: 'current' }))
  await vi.advanceTimersByTimeAsync(1500)
  await settle()
  expect(content(root)).toContain('harness.completed')
  expect(content(root)).toContain('harness.process.restoreFailed')
  expect(content(root)).toContain('Pi worker: Native initialization failed')
})
