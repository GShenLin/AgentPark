import { getActiveApiBase } from './api'
import { getSettingsSection } from './settingsApi'

let appliedVariables = new Set<string>()

export async function applyWorkspaceTheme() {
  const section = await getSettingsSection('theme')
  applyThemeConfig(section.data, section.active_preset_id || '')
}

export function applyThemeConfig(config: Record<string, unknown>, activePresetId = '') {
  const panels = config.panels
  if (!panels || typeof panels !== 'object' || Array.isArray(panels)) return

  const root = document.documentElement
  for (const name of appliedVariables) {
    root.style.removeProperty(name)
  }
  appliedVariables = new Set<string>()

  for (const [panelId, panel] of Object.entries(panels as Record<string, unknown>)) {
    if (!panel || typeof panel !== 'object' || Array.isArray(panel)) continue
    applyPanelTheme(root, `--theme-panel-${kebabCase(panelId)}`, panel as Record<string, unknown>, activePresetId)
  }
}

function applyPanelTheme(root: HTMLElement, prefix: string, panel: Record<string, unknown>, activePresetId: string) {
  for (const [groupId, group] of Object.entries(panel)) {
    if (group && typeof group === 'object' && !Array.isArray(group)) {
      applyStyleGroup(root, `${prefix}-${kebabCase(groupId)}`, group as Record<string, unknown>, activePresetId)
    } else {
      setCssValue(root, `${prefix}-${kebabCase(groupId)}`, group)
    }
  }
}

function applyStyleGroup(root: HTMLElement, prefix: string, group: Record<string, unknown>, activePresetId: string) {
  for (const [key, value] of Object.entries(group)) {
    if (key === 'image') {
      setCssValue(root, `${prefix}-image`, imageCssValue(value, activePresetId))
    } else {
      setCssValue(root, `${prefix}-${kebabCase(key)}`, value)
    }
  }
}

function setCssValue(root: HTMLElement, name: string, value: unknown) {
  if (typeof value !== 'string') return
  const text = value.trim()
  if (!text) return
  root.style.setProperty(name, text)
  appliedVariables.add(name)
}

function imageCssValue(value: unknown, activePresetId: string) {
  if (typeof value !== 'string') return ''
  const image = value.trim().replace(/\\/g, '/').replace(/^\/+/, '')
  if (!image) return 'none'
  const path = image.split('/').filter(Boolean).map(encodeURIComponent).join('/')
  const preset = String(activePresetId || '').trim()
  const query = preset ? `?preset=${encodeURIComponent(preset)}` : ''
  return `url("${getActiveApiBase()}/api/theme/img/${path}${query}")`
}

function kebabCase(value: string) {
  return String(value || '')
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .replace(/[^A-Za-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase()
}
