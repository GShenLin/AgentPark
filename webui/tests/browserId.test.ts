import { afterEach, describe, expect, it, vi } from 'vitest'
import { createBrowserUuid } from '../src/utils/browserId'

describe('createBrowserUuid', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses randomUUID when the browser provides it', () => {
    vi.stubGlobal('crypto', {
      randomUUID: () => '11111111-2222-4333-8444-555555555555',
    })

    expect(createBrowserUuid()).toBe('11111111-2222-4333-8444-555555555555')
  })

  it('builds an RFC 4122 UUID from getRandomValues when randomUUID is unavailable', () => {
    vi.stubGlobal('crypto', {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.set(Array.from({ length: 16 }, (_, index) => index))
        return bytes
      },
    })

    expect(createBrowserUuid()).toBe('00010203-0405-4607-8809-0a0b0c0d0e0f')
  })

  it('reports an explicit compatibility error when secure random values are unavailable', () => {
    vi.stubGlobal('crypto', {})

    expect(() => createBrowserUuid()).toThrow('This browser cannot generate cryptographically secure IDs.')
  })
})
