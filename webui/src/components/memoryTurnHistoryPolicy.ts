import type { MemoryTurnFeedEntry } from './memoryFeedTools'

export function isLatestMemoryTurn(
  entries: readonly Pick<MemoryTurnFeedEntry, 'type'>[],
  index: number,
) {
  for (let candidate = entries.length - 1; candidate >= 0; candidate -= 1) {
    if (entries[candidate]?.type === 'turn') return candidate === index
  }
  return false
}

export function shouldLoadPreviousTurnsOnCollapse(
  entries: readonly Pick<MemoryTurnFeedEntry, 'type'>[],
  index: number,
  expanded: boolean,
  historyComplete: boolean | undefined,
) {
  return !expanded && historyComplete === false && isLatestMemoryTurn(entries, index)
}
