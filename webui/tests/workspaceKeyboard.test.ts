import { describe, expect, it } from 'vitest'
import { resolveWorkspaceEscapeAction } from '../src/workspaceKeyboard'

function escape(defaultPrevented = false) {
  return { key: 'Escape', defaultPrevented }
}

describe('workspace Escape routing', () => {
  it('returns from settings to the board', () => {
    expect(resolveWorkspaceEscapeAction(escape(), {
      activeView: 'settings',
      hasBlockingDialog: false,
    })).toBe('settings-back')
  })

  it('keeps an inner control or modal in charge of Escape', () => {
    expect(resolveWorkspaceEscapeAction(escape(true), {
      activeView: 'settings',
      hasBlockingDialog: false,
    })).toBeNull()
    expect(resolveWorkspaceEscapeAction(escape(), {
      activeView: 'settings',
      hasBlockingDialog: true,
    })).toBeNull()
  })

  it('leaves conversation dismissal to the shared dialog lifecycle', () => {
    expect(resolveWorkspaceEscapeAction(escape(), {
      activeView: 'board',
      hasBlockingDialog: false,
    })).toBeNull()
  })
})
