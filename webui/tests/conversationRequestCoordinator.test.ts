import { describe, expect, it } from 'vitest'
import { ConversationRequestCoordinator } from '../src/conversationRequestCoordinator'

describe('conversation request coordination', () => {
  it('preserves lightweight dialogue bodies when old refresh callers request full history', () => {
    const coordinator = new ConversationRequestCoordinator()
    coordinator.activate('pc/graph/node')
    coordinator.begin('pc/graph/node', 'conversation')
    expect(coordinator.begin('pc/graph/node', 'all').historyMode).toBe('conversation')
    expect(coordinator.begin('pc/graph/node', 'latest_turn').historyMode).toBe('conversation')
  })
  it('prevents an older latest-turn response from replacing a full-history request', () => {
    const coordinator = new ConversationRequestCoordinator()
    coordinator.activate('pc/graph/node')

    const latestTurn = coordinator.begin('pc/graph/node', 'latest_turn')
    const fullHistory = coordinator.begin('pc/graph/node', 'all')

    expect(coordinator.canCommit(latestTurn)).toBe(false)
    expect(coordinator.canCommit(fullHistory)).toBe(true)
  })

  it('keeps automatic refreshes at full-history depth after full history is requested', () => {
    const coordinator = new ConversationRequestCoordinator()
    coordinator.activate('pc/graph/node')

    coordinator.begin('pc/graph/node', 'all')
    const automaticRefresh = coordinator.begin('pc/graph/node', 'latest_turn')

    expect(automaticRefresh.historyMode).toBe('all')
  })

  it('starts an exact replacement request after a destructive conversation change', () => {
    const coordinator = new ConversationRequestCoordinator()
    coordinator.activate('pc/graph/node')

    const fullHistoryBeforeDeletion = coordinator.begin('pc/graph/node', 'all')
    const latestTurnAfterDeletion = coordinator.beginReplacement('pc/graph/node', 'latest_turn')

    expect(latestTurnAfterDeletion.historyMode).toBe('latest_turn')
    expect(coordinator.canCommit(fullHistoryBeforeDeletion)).toBe(false)
    expect(coordinator.canCommit(latestTurnAfterDeletion)).toBe(true)
  })

  it('uses the replacement depth for subsequent automatic refreshes', () => {
    const coordinator = new ConversationRequestCoordinator()
    coordinator.activate('pc/graph/node')

    coordinator.begin('pc/graph/node', 'all')
    coordinator.beginReplacement('pc/graph/node', 'latest_turn')
    const automaticRefresh = coordinator.begin('pc/graph/node', 'latest_turn')

    expect(automaticRefresh.historyMode).toBe('latest_turn')
  })

  it('uses request start order when deciding which response may commit', () => {
    const coordinator = new ConversationRequestCoordinator()
    coordinator.activate('pc/graph/node')

    const sendSnapshot = coordinator.begin('pc/graph/node', 'latest_turn')
    const refreshStartedWhileSending = coordinator.begin('pc/graph/node', 'latest_turn')

    expect(coordinator.canCommit(sendSnapshot)).toBe(false)
    expect(coordinator.canCommit(refreshStartedWhileSending)).toBe(true)
  })

  it('lets a deletion refresh supersede an earlier response for the same node', () => {
    const coordinator = new ConversationRequestCoordinator()
    coordinator.activate('pc/graph/node')

    const beforeDeletion = coordinator.begin('pc/graph/node', 'latest_turn')
    const afterDeletion = coordinator.begin('pc/graph/node', 'latest_turn')

    expect(coordinator.canCommit(beforeDeletion)).toBe(false)
    expect(coordinator.canCommit(afterDeletion)).toBe(true)
  })

  it('invalidates a lazy-section response when a deletion refresh starts later', () => {
    const coordinator = new ConversationRequestCoordinator()
    coordinator.activate('pc/graph/node')
    coordinator.begin('pc/graph/node', 'latest_turn')
    const lazySection = coordinator.captureScope('pc/graph/node')

    coordinator.begin('pc/graph/node', 'latest_turn')

    expect(coordinator.isActiveScope(lazySection)).toBe(false)
  })

  it('rejects responses from an earlier activation of the same node', () => {
    const coordinator = new ConversationRequestCoordinator()
    coordinator.activate('pc/graph/node')
    const earlierVisit = coordinator.begin('pc/graph/node', 'latest_turn')

    coordinator.activate('pc/graph/node')

    expect(coordinator.canCommit(earlierVisit)).toBe(false)
  })

  it('invalidates active requests when the conversation is deactivated', () => {
    const coordinator = new ConversationRequestCoordinator()
    coordinator.activate('pc/graph/node')
    const request = coordinator.begin('pc/graph/node', 'latest_turn')

    coordinator.deactivate()

    expect(coordinator.canCommit(request)).toBe(false)
  })

  it('does not accept lazy-section modes as base conversation replacements', () => {
    const coordinator = new ConversationRequestCoordinator()
    coordinator.activate('pc/graph/node')

    expect(() => coordinator.begin('pc/graph/node', 'latest_turn_progress')).toThrow(
      'Unsupported base conversation history mode',
    )
  })
})
