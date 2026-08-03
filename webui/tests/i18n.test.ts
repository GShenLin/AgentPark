import { afterEach, describe, expect, it } from 'vitest'
import { localeDefinitions, setLocale, t } from '../src/i18n'

afterEach(() => setLocale('en-US'))

describe('i18n catalog', () => {
  it('keeps every configured locale complete', () => {
    const [reference, ...translations] = localeDefinitions
    const expectedKeys = Object.keys(reference.messages).sort()

    for (const locale of translations) {
      expect(Object.keys(locale.messages).sort()).toEqual(expectedKeys)
    }
  })

  it('switches locale and interpolates named parameters', () => {
    setLocale('zh-CN')
    expect(t('mobile.instanceCount', { count: 3 })).toBe('3 个实例')

    setLocale('en-US')
    expect(t('mobile.instanceCount', { count: 3 })).toBe('3 instance')
  })

  it('falls back to the message key for an unknown entry', () => {
    expect(t('missing.translation.key')).toBe('missing.translation.key')
  })
})
