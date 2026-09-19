import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRenderer, nextTick } from 'vue'
import * as Vue from 'vue'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { readFileSync } from 'node:fs'

vi.mock('../src/api', () => ({
  getAccessStatus: async () => ({ username_required: false, is_developer: false }),
  loadWorkspaceBootstrap: async () => ({
    access: { is_developer: false }, user_interactions: [],
    theme: { data: {}, active_preset_id: '' }, mobile_pcs: [{ id: 'local', name: 'Device' }],
  }),
  listMobilePcs: async () => [],
}))
vi.mock('../src/accessIdentity', () => ({ setAccessUsername: vi.fn() }))
vi.mock('../src/theme', () => ({ applyThemeConfig: vi.fn(), applyWorkspaceTheme: vi.fn() }))
vi.mock('../src/i18n', () => ({ t: (key: string) => key }))
vi.mock('../src/composables/useAppEventStream', () => ({ startAppEventStream: () => vi.fn() }))
vi.mock('../src/composables/useUserInteractions', () => ({ primeUserInteractions: vi.fn(), useUserInteractions: vi.fn() }))
vi.mock('../src/composables/useWorkAlerts', () => ({ initializeForegroundAlerts: () => vi.fn() }))
vi.mock('../src/DesktopWorkspace.vue', () => ({ default: { template: '<desktop-workspace />' } }))
vi.mock('../src/mobile/MobileWorkspace.vue', () => ({ default: { template: '<mobile-workspace />' } }))
vi.mock('../src/mobile/MobileUserInteractionDrawer.vue', () => ({ default: { template: '<mobile-interactions />' } }))
vi.mock('../src/components/UserInteractionDialog.vue', () => ({ default: { template: '<desktop-interactions />' } }))
vi.mock('../src/components/AccessUsernameDialog.vue', () => ({ default: { template: '<access-dialog />' } }))
vi.mock('../src/components/WorkAlertToast.vue', () => ({ default: { template: '<alerts />' } }))

import App from '../src/App.vue'

// Vitest's Node transform emits the SSR template; compile the same SFC template
// for the client renderer to exercise reactive viewport switches as well.
const { descriptor } = parse(readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8'))
const bindings = compileScript(descriptor, { id: 'viewport-test' }).bindings
App.render = new Function('Vue', compile(descriptor.template!.content, {
  mode: 'function', prefixIdentifiers: true, bindingMetadata: bindings,
}).code)(Vue)

// A Vue host for testing the real App's component selection without a browser.
type HostNode = { type: string; children: HostNode[]; parent?: HostNode }
const node = (type: string): HostNode => ({ type, children: [] })
const renderer = createRenderer<HostNode, HostNode>({
  createElement: node, createText: () => node('text'), createComment: () => node('comment'),
  setText() {}, setElementText() {}, patchProp() {},
  insert(child, parent, anchor) {
    if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    parent.children.splice(index < 0 ? parent.children.length : index, 0, child)
    child.parent = parent
  },
  remove(child) { child.parent?.children.splice(child.parent.children.indexOf(child), 1) },
  parentNode: (child) => child.parent || null,
  nextSibling: (child) => child.parent?.children[child.parent.children.indexOf(child) + 1] || null,
})
function types(root: HostNode): string[] { return [root.type, ...root.children.flatMap(types)] }
async function settle() {
  for (let i = 0; i < 8; i++) await nextTick()
}
let unmount: (() => void) | undefined
afterEach(() => { unmount?.(); vi.unstubAllGlobals() })

describe('shared workspace viewport routing', () => {
  it.each([false, true])('uses the existing mobile UI and drawer on a phone (cloud=%s)', async (cloud) => {
    const media = { matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }
    vi.stubGlobal('window', { location: { pathname: cloud ? `/board/${'a'.repeat(64)}` : '/', search: '' }, matchMedia: () => media })
    vi.stubGlobal('document', { title: '', querySelector: () => cloud ? {} : null })
    const root = node('root')
    const app = renderer.createApp(App)
    app.provide(Vue.ssrContextKey, { modules: new Set() })
    app.mount(root)
    unmount = () => app.unmount()
    await settle()
    expect(types(root)).toContain('mobile-workspace')
    expect(types(root)).toContain('mobile-interactions')
    expect(types(root)).not.toContain('desktop-workspace')

    // Rotating/resizing into desktop mode reuses the already loaded bootstrap.
    media.matches = false
    media.addEventListener.mock.calls[0]![1]()
    await settle()
    expect(types(root)).toContain('desktop-workspace')
    expect(types(root)).not.toContain('mobile-workspace')
  })
})
