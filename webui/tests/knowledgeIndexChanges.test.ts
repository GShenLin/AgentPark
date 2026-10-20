import { describe, expect, it } from 'vitest'
import { emptyKnowledgeConfig, knowledgeIndexWillChange } from '../src/knowledgeApi'

describe('knowledge index changes', () => {
  const original = { ...emptyKnowledgeConfig(), folder: 'C:/Notes',
    embedding_url: 'https://ark.cn-beijing.volces.com/api/plan/v3/embeddings',
    embedding_model: 'doubao-embedding-vision' }

  it('keeps the existing index for the documented Ark alias and endpoint correction', () => {
    expect(knowledgeIndexWillChange(original, { ...original,
      embedding_url: 'https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal',
      embedding_model: 'doubao-embedding-vision-251215', api_key_alias: 'Ark' })).toBe(false)
  })

  it('identifies changes that require an independent index, but not connection tuning', () => {
    for (const change of [{ embedding_model: 'other' }, { folder: 'D:/Other' },
      { chunk_size: 2000 }, { chunk_overlap: 100 }, { spreadsheet_header_row: 1 }]) {
      expect(knowledgeIndexWillChange(original, { ...original, ...change })).toBe(true)
    }
    expect(knowledgeIndexWillChange(original, { ...original, batch_size: 4, request_timeout: 90 })).toBe(false)
  })
})
