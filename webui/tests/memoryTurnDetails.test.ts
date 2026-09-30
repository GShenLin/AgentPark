import { createSSRApp, effectScope, h, nextTick, ref } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it, vi } from 'vitest'
import type { MessageEnvelope } from '../src/api'
import { useMemoryTurnEntries, type FeedTurnEntry } from '../src/components/memoryFeedTools'
import { useMemoryTurnDetails } from '../src/components/useMemoryTurnDetails'

vi.mock('vue', async original => ({ ...await original<typeof import('vue')>(), onBeforeUnmount: vi.fn() }))
vi.mock('../src/components/MemoryFileDiffDialog.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/components/ImageLightbox.vue', () => ({ default: { render: () => null } }))
import MemoryMessageFeed from '../src/components/MemoryMessageFeed.vue'
import MemoryTurnGroup from '../src/components/MemoryTurnGroup.vue'

function message(id: string, role: string, text: string): MessageEnvelope {
  return { id, role, parts: [{ type: 'text', text }], created_at: '2026-09-27T00:00:00Z' }
}
function user(id: string, revision = 'v1', running = false): MessageEnvelope {
  return { ...message(id, 'user', `question-${id}`), turn_summary: {
    turn_id: id, revision, running, item_count: 1, tool_count: 1, has_metadata: true,
  } }
}
function turn(userMessage = user('u1')): FeedTurnEntry {
  return useMemoryTurnEntries(ref([userMessage, message('a1', 'assistant', 'final-answer')])).value[0] as FeedTurnEntry
}

describe('lazy process per turn', () => {
  it('does not fetch details when a running turn receives new progress', async () => {
    const entry = ref(turn(user('u1', 'v1', true)))
    const loader = vi.fn()
    const scope = effectScope()
    scope.run(() => useMemoryTurnDetails(entry, () => loader))
    entry.value = turn(user('u1', 'v2', true))
    await nextTick()
    expect(loader).not.toHaveBeenCalled()
    scope.stop()
  })
  it('renders old and new dialogue bodies without requesting process data', async () => {
    const loadTurnDetails = vi.fn()
    const html = await renderToString(createSSRApp({ render: () => h(MemoryMessageFeed, {
      messages: [user('u1'), message('a1', 'assistant', 'answer-one'), user('u2'), message('a2', 'assistant', 'answer-two')],
      markdownPreview: true, loadTurnDetails,
    }) }))
    expect(html).toContain('answer-one')
    expect(html).toContain('answer-two')
    expect(html.match(/class="turn-group expanded"/g)).toHaveLength(2)
    expect(html).not.toContain('progress-group-list')
    expect(loadTurnDetails).not.toHaveBeenCalled()
  })

  it('shows Processing on mobile without automatically requesting running details', async () => {
    const loadTurnDetails = vi.fn()
    const html = await renderToString(createSSRApp({ render: () => h(MemoryTurnGroup, {
      entry: turn(user('u1', 'v1', true)), markdownPreview: true, compact: true, loadTurnDetails,
    }) }))
    expect(html).toContain('Processing')
    expect(html).toContain('final-answer')
    expect(html).not.toContain('progress-group-list')
    expect(loadTurnDetails).not.toHaveBeenCalled()
  })

  it('loads the clicked older turn once and keeps it when a newer turn arrives', async () => {
    const entry = ref(turn())
    const loader = vi.fn().mockResolvedValue([user('u1'), message('p1', 'assistant_progress', 'process-detail'), message('a1', 'assistant', 'final-answer')])
    const scope = effectScope()
    const state = scope.run(() => useMemoryTurnDetails(entry, () => loader))!
    expect(loader).not.toHaveBeenCalled()
    await state.load()
    expect(loader).toHaveBeenCalledExactlyOnceWith('u1')
    expect(state.displayEntry.value.progressMessages[0]?.id).toBe('p1')
    entry.value = { ...turn(), startIndex: 10 }
    await nextTick()
    await state.load()
    expect(loader).toHaveBeenCalledTimes(1)
    scope.stop()
  })

  it('shows errors and retries explicitly after a failed load', async () => {
    const loader = vi.fn().mockRejectedValueOnce(new Error('connection failed')).mockResolvedValue([user('u1')])
    const scope = effectScope()
    const state = scope.run(() => useMemoryTurnDetails(ref(turn()), () => loader))!
    await expect(state.load()).rejects.toThrow('connection failed')
    expect(state.loaded.value).toBe(false)
    expect(state.error.value).toBe('connection failed')
    await state.load()
    expect(state.loaded.value).toBe(true)
    expect(state.error.value).toBe('')
    scope.stop()
  })

  it('rejects an obsolete detail response after a revision change', async () => {
    let finishOld!: (messages: MessageEnvelope[]) => void
    const loader = vi.fn().mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
      .mockResolvedValue([user('u1', 'v2'), message('p2', 'assistant_progress', 'new-process')])
    const entry = ref(turn())
    const scope = effectScope()
    const state = scope.run(() => useMemoryTurnDetails(entry, () => loader))!
    const oldRequest = state.load()
    entry.value = turn(user('u1', 'v2'))
    await nextTick()
    await state.load()
    finishOld([user('u1'), message('p1', 'assistant_progress', 'old-process')])
    await oldRequest
    expect(state.displayEntry.value.progressMessages[0]?.id).toBe('p2')
    scope.stop()
  })
})
