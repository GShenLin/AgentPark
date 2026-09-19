import { beforeEach, describe, expect, it, vi } from 'vitest'

const request = vi.hoisted(() => vi.fn())
vi.mock('../src/api', async importOriginal => ({
  ...await importOriginal<typeof import('../src/api')>(),
  getActiveApiBase: () => 'http://localhost:8000',
  requestApiJson: request,
}))

import { ApiHttpError } from '../src/api'
import { emptyKnowledgeConfig, knowledgeCitation, saveKnowledge, type KnowledgeHit } from '../src/knowledgeApi'

beforeEach(() => { request.mockReset() })

describe('Knowledge configuration API', () => {
  it('sends the selected shared key alias without a secret field', async () => {
    request.mockResolvedValue({ id: 'library' })
    await saveKnowledge({ ...emptyKnowledgeConfig(), api_key_alias: 'ark-key' })
    const payload = JSON.parse(request.mock.calls[0]![2].body)
    expect(payload.api_key_alias).toBe('ark-key')
    expect(payload).not.toHaveProperty('api_key')
  })

  it('shows actionable validation messages without dumping submitted config', async () => {
    request.mockRejectedValue(new ApiHttpError(422, JSON.stringify([
      { loc: ['body', 'embedding_url'], msg: '请使用 /api/coding/v3', input: 'private-input' },
    ])))
    await expect(saveKnowledge(emptyKnowledgeConfig())).rejects.toThrow(
      'embedding_url: 请使用 /api/coding/v3')
  })

  it('preserves errors that are not structured validation errors', async () => {
    const error = new ApiHttpError(403, 'owner access required')
    request.mockRejectedValue(error)
    await expect(saveKnowledge(emptyKnowledgeConfig())).rejects.toBe(error)
  })
})

describe('Knowledge source citations', () => {
  const hit = { page: null, line: null, location: {} } as KnowledgeHit
  it('shows Excel coordinates and Word table references without fake line numbers', () => {
    expect(knowledgeCitation({ ...hit, location: { kind: 'spreadsheet', sheet: '销售',
      row_start: 2, row_end: 7, column_start: 'A', column_end: 'C' } })).toBe('销售 · A2:C7')
    expect(knowledgeCitation({ ...hit, location: { kind: 'word', part: 'body', section: '方法',
      table: 2, row_start: 3 } })).toBe('body · 方法 · 表 2 第 3 行')
    expect(knowledgeCitation({ ...hit, page: 4 })).toBe('第 4 页')
    expect(knowledgeCitation({ ...hit, line: 9 })).toBe('第 9 行')
    expect(knowledgeCitation(hit)).toBe('文档片段')
  })
})
