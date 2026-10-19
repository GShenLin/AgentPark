import { afterEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, reactive } from 'vue'
import { useOpenCodeOptions } from '../src/composables/useOpenCodeOptions'
import { getOpenCodeOptions, type OpenCodeOptions } from '../src/harnessApi'

vi.mock('../src/harnessApi', () => ({ getOpenCodeOptions: vi.fn() }))
const result = (effort: string): OpenCodeOptions => ({ native_model: [{ value: 'p/m', label: 'Model' }],
  native_agent: [{ value: 'build', label: 'Build' }], native_effort: [{ value: effort, label: effort }], selection_error: '' })
afterEach(() => { vi.useRealTimers(); vi.resetAllMocks() })

describe('OpenCode native selections', () => {
  it('loads actual options without changing saved fields and rejects stale responses', async () => {
    vi.useFakeTimers()
    let first!: (value: OpenCodeOptions) => void
    vi.mocked(getOpenCodeOptions).mockImplementationOnce(() => new Promise(resolve => { first = resolve }))
      .mockResolvedValueOnce(result('high'))
    const props = reactive({ typeId: 'opencode_node', fields: { native_model: 'p/old', native_agent: 'build', native_effort: 'max' } })
    const scope = effectScope()
    const state = scope.run(() => useOpenCodeOptions(props))!
    await vi.advanceTimersByTimeAsync(150)
    props.fields.native_model = 'p/m'
    await nextTick()
    await vi.advanceTimersByTimeAsync(150)
    first(result('low'))
    await nextTick()
    expect(state.catalog.options.native_effort.map(x => x.value)).toEqual(['', 'high'])
    expect(props.fields.native_effort).toBe('max')
    expect(state.catalog.loading).toBe(false)
    props.fields = { ...props.fields, native_effort: 'high' }
    await nextTick()
    await vi.advanceTimersByTimeAsync(150)
    expect(getOpenCodeOptions).toHaveBeenCalledTimes(2)
    scope.stop()
  })
  it('surfaces discovery errors instead of presenting cached choices', async () => {
    vi.useFakeTimers()
    vi.mocked(getOpenCodeOptions).mockRejectedValue(new Error('CLI unavailable'))
    const scope = effectScope()
    const state = scope.run(() => useOpenCodeOptions(reactive({ typeId: 'opencode_node', fields: {} })))!
    await vi.advanceTimersByTimeAsync(150)
    expect(state.catalog.error).toBe('CLI unavailable')
    expect(state.catalog.options.native_model).toEqual([])
    scope.stop()
  })
})
