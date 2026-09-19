import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const api = vi.hoisted(() => ({ listMobilePcs: vi.fn(), listMobileGraphs: vi.fn(), listGraphProfiles: vi.fn() }))
vi.mock('../src/api', async (original) => ({ ...await original<typeof import('../src/api')>(), ...api }))
vi.mock('vue', async (original) => ({ ...await original<typeof import('vue')>(), onBeforeUnmount: vi.fn() }))
vi.mock('../src/composables/useGlobalState', () => ({ useGlobalState: () => ({ nodeTriggerInputs: ref({}) }) }))

import { useMobileWorkspace } from '../src/mobile/useMobileWorkspace'

beforeEach(() => {
  vi.clearAllMocks()
  api.listMobilePcs.mockResolvedValue([{ id: 'local', name: 'Selected device' }])
  api.listMobileGraphs.mockResolvedValue([{ id: 'runtime', graphs: [] }])
  api.listGraphProfiles.mockResolvedValue([])
})

describe('mobile workspace entry', () => {
  it('opens the selected cloud device graph list without another PC selection', async () => {
    const workspace = useMobileWorkspace({ initialPcId: 'local' })
    await workspace.loadPcs()
    expect(workspace.view.value).toBe('graphs')
    expect(workspace.selectedPc.value?.id).toBe('local')
    expect(api.listMobileGraphs).toHaveBeenCalledExactlyOnceWith('local')
    expect(workspace.loading.value).toBe(false)
    expect(workspace.error.value).toBe('')
  })
  it('keeps the existing PC chooser for direct mobile access', async () => {
    const workspace = useMobileWorkspace()
    await workspace.loadPcs()
    expect(workspace.view.value).toBe('pcs')
    expect(api.listMobileGraphs).not.toHaveBeenCalled()
  })
  it('reports a missing device without silently selecting another one', async () => {
    api.listMobilePcs.mockResolvedValue([{ id: 'other', name: 'Other device' }])
    const workspace = useMobileWorkspace({ initialPcId: 'local' })
    await workspace.loadPcs()
    expect(workspace.error.value).toContain('PC not found: local')
    expect(api.listMobileGraphs).not.toHaveBeenCalled()
    expect(workspace.loading.value).toBe(false)
  })
})
