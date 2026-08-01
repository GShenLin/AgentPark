import { describe, expect, it } from 'vitest'
import type { MessageEnvelope } from '../src/api'
import { resolveTurnDeletionHistoryMode } from '../src/turnDeletionRefresh'

function message(id: string, role: MessageEnvelope['role']): MessageEnvelope {
  return { id, role, parts: [], created_at: `2026-07-29T00:00:0${id.length}Z` }
}

describe('turn deletion refresh policy', () => {
  it('loads the previous turn after deleting the latest loaded turn', () => {
    expect(resolveTurnDeletionHistoryMode([
      message('user-1', 'user'),
      message('assistant-1', 'assistant'),
      message('user-2', 'user'),
      message('assistant-2', 'assistant'),
    ], 'user-2', false)).toBe('latest_turn')
  })

  it('preserves complete history when deleting an older turn', () => {
    expect(resolveTurnDeletionHistoryMode([
      message('user-1', 'user'),
      message('assistant-1', 'assistant'),
      message('user-2', 'user'),
      message('assistant-2', 'assistant'),
    ], 'user-1', true)).toBe('all')
  })

  it('falls back to the latest remaining turn when only a partial history is loaded', () => {
    expect(resolveTurnDeletionHistoryMode([], 'user-2', false)).toBe('latest_turn')
  })
})
