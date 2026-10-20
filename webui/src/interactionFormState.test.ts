import { describe, expect, it } from 'vitest'
import { clearInteractionDraft, getInteractionDraft, saveInteractionDraft, validateInteractionDraft } from './interactionFormState'
import type { UserInteractionRequest } from './apiTypes'

function storage(): Storage {
  const values = new Map<string, string>()
  return { get length() { return values.size }, clear: () => values.clear(),
    getItem: key => values.get(key) ?? null, setItem: (key, value) => { values.set(key, value) },
    removeItem: key => { values.delete(key) }, key: index => [...values.keys()][index] ?? null }
}
function request(id: string): UserInteractionRequest {
  return { id, status: 'pending', schema: { title: 'Review', fields: [
    { id: 'note', type: 'textarea', label: 'Note', required: true },
    { id: 'choice', type: 'multiselect', label: 'Choice', required: true, options: [{ value: 'a', label: 'A' }, { value: 'b', label: 'B', disabled: true }] },
    { id: 'confirm', type: 'checkbox', label: 'Confirm', required: true },
    { id: 'file', type: 'file', label: 'File', required: true },
  ] } }
}

describe('interaction drafts and answer contracts', () => {
  it('preserves each request when switching and separates server origins', () => {
    const store = storage(), first = request('switch-a'), second = request('switch-b')
    const draft = getInteractionDraft(first, 'server-a', store)
    draft.values.note = 'unfinished'
    getInteractionDraft(second, 'server-a', store).values.note = 'other'
    expect(getInteractionDraft(first, 'server-a', store).values.note).toBe('unfinished')
    expect(getInteractionDraft(first, 'server-b', store).values.note).toBe('')
  })

  it('persists values and uploaded attachments without serializing browser File handles', () => {
    const store = storage(), first = request('persist')
    const draft = getInteractionDraft(first, 'server', store)
    draft.values.note = 'saved'
    draft.uploaded.file = [{ name: 'a.txt', path: '/uploads/a.txt', size: 1, kind: 'file', mime: 'text/plain', source: 'upload' }]
    saveInteractionDraft(first.id, 'server', draft, store)
    const serialized = store.getItem(store.key(0)!)!
    expect(JSON.parse(serialized).values.note).toBe('saved')
    expect(JSON.parse(serialized)).not.toHaveProperty('selectedFiles')
    expect(JSON.parse(serialized).uploaded.file[0].path).toBe('/uploads/a.txt')
    clearInteractionDraft(first.id, 'server', store)
    expect(store.length).toBe(0)
    expect(getInteractionDraft(first, 'server', store).values.note).toBe('')
  })

  it('validates all controls before uploading or submitting', () => {
    const pending = request('validation'), draft = getInteractionDraft(pending, 'server', storage())
    expect(Object.keys(validateInteractionDraft(pending.schema.fields, draft))).toHaveLength(4)
    draft.values = { note: 'OK', choice: ['a'], confirm: true }
    draft.uploaded.file = [{ name: 'a.txt', path: '/uploads/a.txt', size: 1, kind: 'file', mime: 'text/plain', source: 'upload' }]
    expect(validateInteractionDraft(pending.schema.fields, draft)).toEqual({})
    draft.values.choice = ['b']
    expect(validateInteractionDraft(pending.schema.fields, draft)).toHaveProperty('choice')
    draft.values.choice = ['a', 'a']
    expect(validateInteractionDraft(pending.schema.fields, draft)).toHaveProperty('choice')
    draft.values.confirm = 'true'
    expect(validateInteractionDraft(pending.schema.fields, draft)).toHaveProperty('confirm')
  })
})
