export type WorkspaceEscapeAction = 'settings-back' | null

export type WorkspaceEscapeState = {
  activeView: 'board' | 'settings'
  hasBlockingDialog: boolean
}

export function resolveWorkspaceEscapeAction(
  event: Pick<KeyboardEvent, 'key' | 'defaultPrevented'>,
  state: WorkspaceEscapeState,
): WorkspaceEscapeAction {
  if (event.key !== 'Escape' || event.defaultPrevented || state.hasBlockingDialog) return null
  if (state.activeView === 'settings') return 'settings-back'
  return null
}
