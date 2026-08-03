export type SupportedLocale = 'en-US' | 'zh-CN'

export type MessageParameters = Record<string, string | number>

export type LocaleDefinition = {
  code: SupportedLocale
  label: string
  shortLabel: string
  messages: Record<string, string>
}
