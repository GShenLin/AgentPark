import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createSettingsPageNavigation } from '../src/components/settings/settingsNavigation'

function setup(compact = true) {
  const options = {
    compact: ref(compact), busy: ref(false), hasChanges: ref(false),
    confirmDiscard: vi.fn(() => false), exit: vi.fn(),
  }
  return { ...options, ...createSettingsPageNavigation(options) }
}

describe('settings navigation and draft protection', () => {
  it('returns detail -> list -> catalog -> workspace without discarding a draft inside settings', () => {
    const state = setup()
    state.sectionOpen.value = true
    state.hasChanges.value = true
    let detail = true
    state.detailBack.value = () => {
      if (!detail) return false
      detail = false
      return true
    }
    state.handleBack()
    expect(detail).toBe(false)
    expect(state.sectionOpen.value).toBe(true)
    state.handleBack()
    expect(state.sectionOpen.value).toBe(false)
    expect(state.confirmDiscard).not.toHaveBeenCalled()
    state.handleBack()
    expect(state.confirmDiscard).toHaveBeenCalledOnce()
    expect(state.exit).not.toHaveBeenCalled()
    state.confirmDiscard.mockReturnValue(true)
    state.handleBack()
    expect(state.exit).toHaveBeenCalledOnce()
  })

  it('does not call the hidden panel back handler from the catalog', () => {
    const state = setup()
    state.detailBack.value = vi.fn(() => true)
    state.handleBack()
    expect(state.detailBack.value).not.toHaveBeenCalled()
    expect(state.exit).toHaveBeenCalledOnce()
  })

  it('protects section switching and reloads with the same discard decision', () => {
    const state = setup()
    expect(state.confirmLeave()).toBe(true)
    expect(state.confirmDiscard).not.toHaveBeenCalled()
    state.hasChanges.value = true
    expect(state.confirmLeave()).toBe(false)
    state.confirmDiscard.mockReturnValue(true)
    expect(state.confirmLeave()).toBe(true)
  })

  it('blocks return and section changes while a load or save is pending', () => {
    const state = setup()
    state.sectionOpen.value = true
    state.busy.value = true
    state.handleBack()
    expect(state.sectionOpen.value).toBe(true)
    expect(state.confirmLeave()).toBe(false)
    expect(state.confirmDiscard).not.toHaveBeenCalled()
    expect(state.exit).not.toHaveBeenCalled()
  })

  it('preserves desktop back behavior and ignores mobile detail navigation', () => {
    const state = setup(false)
    state.sectionOpen.value = true
    state.detailBack.value = vi.fn(() => true)
    state.hasChanges.value = true
    state.handleBack()
    expect(state.confirmDiscard).toHaveBeenCalledOnce()
    expect(state.detailBack.value).not.toHaveBeenCalled()
    expect(state.exit).not.toHaveBeenCalled()
    state.hasChanges.value = false
    state.handleBack()
    expect(state.exit).toHaveBeenCalledOnce()
  })
})
