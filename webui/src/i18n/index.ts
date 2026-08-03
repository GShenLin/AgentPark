import { computed, readonly, ref } from 'vue'
import enUS from './locales/en-US'
import zhCN from './locales/zh-CN'
import type { LocaleDefinition, MessageParameters, SupportedLocale } from './types'

const STORAGE_KEY = 'agentpark.locale'

export const localeDefinitions = [enUS, zhCN] as const satisfies readonly LocaleDefinition[]
const definitionByCode = new Map(localeDefinitions.map((definition) => [definition.code, definition]))

function isSupportedLocale(value: unknown): value is SupportedLocale {
  return typeof value === 'string' && definitionByCode.has(value as SupportedLocale)
}

function detectInitialLocale(): SupportedLocale {
  if (typeof window === 'undefined') return 'en-US'
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (isSupportedLocale(stored)) return stored
  } catch {
    // Browser privacy settings may make localStorage unavailable.
  }
  return window.navigator.language.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US'
}

const activeLocale = ref<SupportedLocale>(detectInitialLocale())

function applyDocumentLanguage(locale: SupportedLocale) {
  if (typeof document !== 'undefined') document.documentElement.lang = locale
}

function interpolate(message: string, parameters: MessageParameters = {}) {
  return message.replace(/\{([A-Za-z0-9_]+)\}/g, (placeholder, key: string) => {
    const value = parameters[key]
    return value === undefined ? placeholder : String(value)
  })
}

export function t(key: string, parameters?: MessageParameters) {
  const definition = definitionByCode.get(activeLocale.value) || enUS
  const fallback = enUS.messages[key]
  return interpolate(definition.messages[key] ?? fallback ?? key, parameters)
}

export function setLocale(locale: SupportedLocale) {
  if (!isSupportedLocale(locale)) return
  activeLocale.value = locale
  applyDocumentLanguage(locale)
  try {
    window.localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    // The active in-memory locale still applies when storage is unavailable.
  }
}

export function cycleLocale() {
  const index = localeDefinitions.findIndex((definition) => definition.code === activeLocale.value)
  const next = localeDefinitions[(index + 1) % localeDefinitions.length] ?? enUS
  setLocale(next.code)
}

export function initializeI18n() {
  applyDocumentLanguage(activeLocale.value)
  if (typeof window === 'undefined') return () => undefined
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY && isSupportedLocale(event.newValue)) {
      activeLocale.value = event.newValue
      applyDocumentLanguage(event.newValue)
    }
  }
  window.addEventListener('storage', onStorage)
  return () => window.removeEventListener('storage', onStorage)
}

export function useI18n() {
  const currentLocale = computed(() => definitionByCode.get(activeLocale.value) || enUS)
  const nextLocale = computed(() => {
    const index = localeDefinitions.findIndex((definition) => definition.code === activeLocale.value)
    return localeDefinitions[(index + 1) % localeDefinitions.length] ?? enUS
  })
  return {
    locale: readonly(activeLocale),
    currentLocale,
    nextLocale,
    localeDefinitions,
    setLocale,
    cycleLocale,
    t,
  }
}

export type { LocaleDefinition, MessageParameters, SupportedLocale } from './types'
