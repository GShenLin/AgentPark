import type { MemoryHistoryMode } from './api'

export type ConversationBaseHistoryMode = Extract<MemoryHistoryMode, 'latest_turn' | 'all'>

export type ConversationRequestScope = {
  selectionKey: string
  activation: number
  requestId: number
}

export type ConversationRequestToken = ConversationRequestScope & {
  historyMode: ConversationBaseHistoryMode
}

function requireBaseHistoryMode(historyMode: MemoryHistoryMode): ConversationBaseHistoryMode {
  if (historyMode === 'latest_turn' || historyMode === 'all') return historyMode
  throw new Error(`Unsupported base conversation history mode: ${historyMode}`)
}

export class ConversationRequestCoordinator {
  private selectionKey = ''
  private activation = 0
  private nextRequestId = 0
  private latestRequestId = 0
  private desiredHistoryMode: ConversationBaseHistoryMode = 'latest_turn'

  activate(selectionKey: string) {
    if (!selectionKey) throw new Error('Conversation selection key is required')
    this.selectionKey = selectionKey
    this.activation += 1
    this.latestRequestId = 0
    this.desiredHistoryMode = 'latest_turn'
  }

  deactivate() {
    this.selectionKey = ''
    this.activation += 1
    this.latestRequestId = 0
    this.desiredHistoryMode = 'latest_turn'
  }

  captureScope(selectionKey: string): ConversationRequestScope {
    this.requireActiveSelection(selectionKey)
    return {
      selectionKey,
      activation: this.activation,
      requestId: this.latestRequestId,
    }
  }

  resolveHistoryMode(
    selectionKey: string,
    requestedHistoryMode: MemoryHistoryMode,
  ): ConversationBaseHistoryMode {
    this.requireActiveSelection(selectionKey)
    const requested = requireBaseHistoryMode(requestedHistoryMode)
    if (requested === 'all') this.desiredHistoryMode = 'all'
    return this.desiredHistoryMode === 'all' ? 'all' : requested
  }

  begin(
    selectionKey: string,
    requestedHistoryMode: MemoryHistoryMode,
  ): ConversationRequestToken {
    const historyMode = this.resolveHistoryMode(selectionKey, requestedHistoryMode)
    return this.issueRequest(selectionKey, historyMode)
  }

  beginReplacement(
    selectionKey: string,
    requestedHistoryMode: MemoryHistoryMode,
  ): ConversationRequestToken {
    this.requireActiveSelection(selectionKey)
    const historyMode = requireBaseHistoryMode(requestedHistoryMode)
    this.desiredHistoryMode = historyMode
    return this.issueRequest(selectionKey, historyMode)
  }

  private issueRequest(
    selectionKey: string,
    historyMode: ConversationBaseHistoryMode,
  ): ConversationRequestToken {
    const requestId = ++this.nextRequestId
    this.latestRequestId = requestId
    return {
      selectionKey,
      activation: this.activation,
      requestId,
      historyMode,
    }
  }

  isActiveScope(scope: ConversationRequestScope) {
    return scope.selectionKey === this.selectionKey
      && scope.activation === this.activation
      && scope.requestId === this.latestRequestId
  }

  canCommit(token: ConversationRequestToken) {
    return this.isActiveScope(token)
  }

  private requireActiveSelection(selectionKey: string) {
    if (selectionKey !== this.selectionKey) {
      throw new Error('Conversation request does not match the active selection')
    }
  }
}
