<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { uploadThemeAsset } from '../../settingsApi'

const props = defineProps<{
  data: Record<string, unknown>
  presets?: Array<{ id: string; path: string }>
  activePresetId?: string
}>()

const emit = defineEmits<{
  'update:data': [value: Record<string, unknown>]
  'load-preset': [presetId: string]
  'save-preset': [presetId: string]
  'refresh-presets': []
}>()

const selectedPanelId = ref('')
const selectedPresetId = ref('')
const savePresetId = ref('')
const imageFileInput = ref<HTMLInputElement | null>(null)
const pendingImageTarget = ref<{ groupId: string; key: string } | null>(null)
const assetUploadingKey = ref('')
const assetUploadError = ref('')

const NON_COLOR_KEYS = new Set(['image', 'size', 'position', 'repeat', 'blendMode'])
const COLOR_FIELD_RE = /(^color$|background|text|border|primary|secondary|muted|accent|danger|selected|focus|hover|active|title|body)/i
const PANEL_LABELS: Record<string, string> = {
  app: 'App Shell',
  boardCanvas: 'Board Canvas',
  graphPanel: 'Graph Panel',
  filePanel: 'File Panel',
  memoryPanel: 'Memory Panel',
  nodeCard: 'Node Card',
  nodePalette: 'Node Palette',
  nodeSideEditor: 'Node Side Editor',
  nodeOutputRoutes: 'Node Output Routes',
  canvasContextMenu: 'Canvas Menu',
  nodeContextMenu: 'Node Menu',
  settingsPanel: 'Settings Panel',
  topbar: 'Top Bar',
}
const PALETTE_COLORS = [
  '#0f172a',
  '#1e293b',
  '#334155',
  '#f8fafc',
  '#94a3b8',
  '#38bdf8',
  '#60a5fa',
  '#6366f1',
  '#a855f7',
  '#ec4899',
  '#f43f5e',
  '#f97316',
  '#eab308',
  '#22c55e',
  '#14b8a6',
  '#000000',
]

type RgbaColor = {
  r: number
  g: number
  b: number
  a: number
}

const panels = computed<Record<string, Record<string, unknown>>>(() => {
  const value = props.data.panels
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, Record<string, unknown>>
    : {}
})

const panelIds = computed(() => Object.keys(panels.value))
const selectedPanel = computed(() => panels.value[selectedPanelId.value] || null)
const selectedGroups = computed(() => {
  const panel = selectedPanel.value
  if (!panel) return []
  return Object.entries(panel)
    .filter(([, value]) => value && typeof value === 'object' && !Array.isArray(value))
    .map(([id, fields]) => ({
      id,
      fields: fields as Record<string, unknown>,
      entries: Object.entries(fields as Record<string, unknown>),
    }))
})

watch(
  panelIds,
  (ids) => {
    if (!ids.includes(selectedPanelId.value)) {
      selectedPanelId.value = ids[0] || ''
    }
  },
  { immediate: true },
)

watch(
  () => props.activePresetId,
  (value) => {
    const active = String(value || 'default').trim() || 'default'
    selectedPresetId.value = active
    if (!savePresetId.value) {
      savePresetId.value = active
    }
  },
  { immediate: true },
)

watch(
  () => props.presets,
  () => {
    const active = String(props.activePresetId || '').trim()
    if (active) selectedPresetId.value = active
  },
)

function cloneData() {
  return JSON.parse(JSON.stringify(props.data || {})) as Record<string, unknown>
}

function fieldText(groupId: string, key: string) {
  const group = selectedPanel.value?.[groupId]
  const fields = group && typeof group === 'object' && !Array.isArray(group)
    ? group as Record<string, unknown>
    : {}
  const value = fields[key]
  return value === null || value === undefined ? '' : String(value)
}

function panelSummary(panelId: string) {
  const background = panels.value[panelId]?.background
  if (!background || typeof background !== 'object' || Array.isArray(background)) return ''
  const item = background as Record<string, unknown>
  return String(item.image || item.color || '')
}

function panelLabel(panelId: string) {
  return PANEL_LABELS[panelId] || panelId
}

function colorPickerHex(groupId: string, key: string) {
  return rgbaToHex(parseColor(fieldText(groupId, key)) || { r: 2, g: 6, b: 23, a: 1 })
}

function colorOpacity(groupId: string, key: string) {
  const color = parseColor(fieldText(groupId, key))
  return Math.round((color?.a ?? 1) * 100)
}

function setColorFromPicker(groupId: string, key: string, hex: string) {
  const next = parseHexColor(hex)
  if (!next) return
  const current = parseColor(fieldText(groupId, key))
  setPanelField(groupId, key, rgbaCss({ ...next, a: current?.a ?? 1 }))
}

function setColorOpacity(groupId: string, key: string, value: string) {
  const current = parseColor(fieldText(groupId, key)) || { r: 2, g: 6, b: 23, a: 1 }
  const opacity = Number(value)
  const a = Number.isFinite(opacity) ? clamp(opacity, 0, 100) / 100 : current.a
  setPanelField(groupId, key, rgbaCss({ ...current, a }))
}

function setPaletteColor(groupId: string, key: string, hex: string) {
  const next = parseHexColor(hex)
  if (!next) return
  const current = parseColor(fieldText(groupId, key))
  setPanelField(groupId, key, rgbaCss({ ...next, a: current?.a ?? 1 }))
}

function setTransparent(groupId: string, key: string) {
  setPanelField(groupId, key, 'transparent')
}

function setPanelField(groupId: string, key: string, value: unknown) {
  const panelId = selectedPanelId.value
  if (!panelId) return
  const next = cloneData()
  const nextPanels = {
    ...(next.panels && typeof next.panels === 'object' && !Array.isArray(next.panels)
      ? next.panels as Record<string, unknown>
      : {}),
  }
  const panel = {
    ...(nextPanels[panelId] && typeof nextPanels[panelId] === 'object' && !Array.isArray(nextPanels[panelId])
      ? nextPanels[panelId] as Record<string, unknown>
      : {}),
  }
  const group = {
    ...(panel[groupId] && typeof panel[groupId] === 'object' && !Array.isArray(panel[groupId])
      ? panel[groupId] as Record<string, unknown>
      : {}),
  }
  if (value === '' || value === null || value === undefined) {
    delete group[key]
  } else {
    group[key] = value
  }
  panel[groupId] = group
  nextPanels[panelId] = panel
  next.panels = nextPanels
  emit('update:data', next)
}

function isColorField(groupId: string, key: string, value: unknown) {
  if (NON_COLOR_KEYS.has(key)) return false
  if (groupId === 'font' || /font(?:size)?$/i.test(key)) return false
  const text = String(value ?? '').trim()
  return Boolean(parseColor(text) || COLOR_FIELD_RE.test(`${groupId} ${key}`))
}

function selectOptionsFor(key: string) {
  if (key === 'size') return ['', 'cover', 'contain', 'auto']
  if (key === 'repeat') return ['', 'no-repeat', 'repeat', 'repeat-x', 'repeat-y']
  if (key === 'blendMode') return ['', 'normal', 'multiply', 'screen', 'overlay', 'soft-light']
  return []
}

function inputValue(event: Event) {
  return (event.target as HTMLInputElement | HTMLSelectElement).value
}

function requestLoadPreset() {
  const presetId = String(selectedPresetId.value || '').trim()
  if (!presetId) return
  emit('load-preset', presetId)
}

function requestSavePreset() {
  const presetId = String(savePresetId.value || '').trim()
  if (!presetId) return
  emit('save-preset', presetId)
}

function openImagePicker(groupId: string, key: string) {
  if (assetUploadingKey.value) return
  pendingImageTarget.value = { groupId, key }
  assetUploadError.value = ''
  if (imageFileInput.value) {
    imageFileInput.value.value = ''
    imageFileInput.value.click()
  }
}

async function handleImageFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  const target = pendingImageTarget.value
  input.value = ''
  if (!file || !target) return
  const uploadKey = `${target.groupId}.${target.key}`
  assetUploadingKey.value = uploadKey
  assetUploadError.value = ''
  try {
    const uploaded = await uploadThemeAsset(file, props.activePresetId || selectedPresetId.value || 'default')
    setPanelField(target.groupId, target.key, uploaded.asset_path)
  } catch (e: any) {
    assetUploadError.value = String(e?.message || e)
  } finally {
    assetUploadingKey.value = ''
    pendingImageTarget.value = null
  }
}

function parseColor(value: string): RgbaColor | null {
  const text = String(value || '').trim()
  if (text.toLowerCase() === 'transparent') {
    return { r: 0, g: 0, b: 0, a: 0 }
  }
  const hex = parseHexColor(text)
  if (hex) return hex
  const match = text.match(/^rgba?\(\s*([.\d]+)\s*,\s*([.\d]+)\s*,\s*([.\d]+)(?:\s*,\s*([.\d]+)\s*)?\)$/i)
  if (!match) return null
  return {
    r: clamp(Number(match[1]), 0, 255),
    g: clamp(Number(match[2]), 0, 255),
    b: clamp(Number(match[3]), 0, 255),
    a: clamp(match[4] == null ? 1 : Number(match[4]), 0, 1),
  }
}

function parseHexColor(value: string): RgbaColor | null {
  const text = String(value || '').trim()
  const match = text.match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i)
  if (!match) return null
  const raw = String(match[1] || '')
  const hex = raw.length === 3
    ? raw.split('').map((item) => `${item}${item}`).join('')
    : raw
  return {
    r: Number.parseInt(hex.slice(0, 2), 16),
    g: Number.parseInt(hex.slice(2, 4), 16),
    b: Number.parseInt(hex.slice(4, 6), 16),
    a: 1,
  }
}

function rgbaToHex(color: RgbaColor) {
  return `#${hexByte(color.r)}${hexByte(color.g)}${hexByte(color.b)}`
}

function rgbaCss(color: RgbaColor) {
  return `rgba(${Math.round(color.r)}, ${Math.round(color.g)}, ${Math.round(color.b)}, ${formatAlpha(color.a)})`
}

function hexByte(value: number) {
  return Math.round(clamp(value, 0, 255)).toString(16).padStart(2, '0')
}

function formatAlpha(value: number) {
  return String(Math.round(clamp(value, 0, 1) * 100) / 100)
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  return Math.max(min, Math.min(max, value))
}
</script>

<template>
  <div class="theme-form">
    <input
      ref="imageFileInput"
      class="hidden-file-input"
      type="file"
      accept="image/*"
      @change="handleImageFileChange"
    />
    <section class="settings-group preset-group">
      <div class="group-head">
        <div>
          <h2>Presets</h2>
          <div class="preset-active">Active: {{ props.activePresetId || 'default' }}</div>
        </div>
        <button type="button" class="preset-btn" @click="emit('refresh-presets')">Refresh</button>
      </div>
      <div class="preset-grid">
        <label>
          <span>Load Preset</span>
          <div class="preset-row">
            <select v-model="selectedPresetId">
              <option v-for="preset in props.presets || []" :key="preset.id" :value="preset.id">
                {{ preset.id }}
              </option>
            </select>
            <button type="button" class="preset-btn" :disabled="!selectedPresetId" @click="requestLoadPreset">Load</button>
          </div>
        </label>
        <label>
          <span>Save Preset</span>
          <div class="preset-row">
            <input v-model="savePresetId" placeholder="preset_id" />
            <button type="button" class="preset-btn" :disabled="!savePresetId" @click="requestSavePreset">Save</button>
          </div>
        </label>
      </div>
    </section>

    <section class="settings-group">
      <div class="group-head">
        <h2>Theme Panels</h2>
      </div>

      <div class="theme-layout">
        <nav class="panel-list">
          <button
            v-for="panelId in panelIds"
            :key="panelId"
            type="button"
            class="panel-item"
            :class="{ active: selectedPanelId === panelId }"
            @click="selectedPanelId = panelId"
          >
            <span>{{ panelLabel(panelId) }}</span>
            <small>{{ panelSummary(panelId) }}</small>
          </button>
        </nav>

        <div v-if="selectedPanel" class="panel-fields">
          <div class="form-head">
            <h3>{{ panelLabel(selectedPanelId) }}</h3>
          </div>
          <div class="panel-groups">
            <section v-for="group in selectedGroups" :key="group.id" class="theme-group">
              <h4>{{ group.id }}</h4>
              <div class="form-grid">
                <label v-for="[key, value] in group.entries" :key="`${group.id}.${key}`" :class="{ 'color-field': isColorField(group.id, key, value) }">
                  <span>{{ key }}</span>
                  <template v-if="isColorField(group.id, key, value)">
                    <div class="color-row">
                      <input
                        class="color-picker"
                        type="color"
                        :value="colorPickerHex(group.id, key)"
                        @input="setColorFromPicker(group.id, key, inputValue($event))"
                      />
                      <input
                        class="color-text"
                        :value="fieldText(group.id, key)"
                        @input="setPanelField(group.id, key, inputValue($event))"
                      />
                    </div>
                    <div class="palette-row" aria-label="Color palette">
                      <button
                        v-for="color in PALETTE_COLORS"
                        :key="`${group.id}.${key}.${color}`"
                        type="button"
                        class="palette-swatch"
                        :style="{ background: color }"
                        :title="color"
                        @click="setPaletteColor(group.id, key, color)"
                      ></button>
                      <button
                        type="button"
                        class="palette-swatch transparent"
                        title="transparent"
                        @click="setTransparent(group.id, key)"
                      ></button>
                    </div>
                    <div class="opacity-row">
                      <input
                        type="range"
                        min="0"
                        max="100"
                        :value="colorOpacity(group.id, key)"
                        @input="setColorOpacity(group.id, key, inputValue($event))"
                      />
                      <span>{{ colorOpacity(group.id, key) }}%</span>
                    </div>
                  </template>
                  <template v-else-if="selectOptionsFor(key).length">
                    <select :value="fieldText(group.id, key)" @change="setPanelField(group.id, key, inputValue($event))">
                      <option v-for="option in selectOptionsFor(key)" :key="option" :value="option">{{ option || 'Unset' }}</option>
                    </select>
                  </template>
                  <template v-else-if="key === 'image'">
                    <div class="asset-row">
                      <input
                        :value="fieldText(group.id, key)"
                        placeholder="example.png"
                        @input="setPanelField(group.id, key, inputValue($event))"
                      />
                      <button
                        type="button"
                        class="asset-btn"
                        :disabled="assetUploadingKey !== ''"
                        @click="openImagePicker(group.id, key)"
                      >
                        {{ assetUploadingKey === `${group.id}.${key}` ? 'Uploading' : 'Browse' }}
                      </button>
                    </div>
                  </template>
                  <template v-else>
                    <input
                      :value="fieldText(group.id, key)"
                      :placeholder="key === 'image' ? 'example.png' : ''"
                      @input="setPanelField(group.id, key, inputValue($event))"
                    />
                  </template>
                </label>
              </div>
            </section>
          </div>
          <div v-if="assetUploadError" class="asset-error">{{ assetUploadError }}</div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.theme-form {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-right: 4px;
}

.hidden-file-input {
  display: none;
}

.settings-group {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  padding: 12px;
  background: rgba(15, 23, 42, 0.28);
}

.preset-group {
  flex: 0 0 auto;
}

.settings-group h2,
.form-head h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.group-head,
.form-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.preset-active {
  margin-top: 3px;
  color: rgba(148, 163, 184, 0.82);
  font-size: 12px;
}

.preset-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 1fr));
  gap: 12px;
}

.preset-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.preset-btn {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.72);
  color: rgba(248, 250, 252, 0.96);
  padding: 7px 10px;
  font-size: 12px;
}

.theme-layout {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 12px;
}

.panel-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.panel-item {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.52);
  color: rgba(226, 232, 240, 0.92);
  padding: 8px;
  text-align: left;
  cursor: pointer;
}

.panel-item.active {
  border-color: rgba(125, 211, 252, 0.5);
  background: rgba(14, 116, 144, 0.22);
}

.panel-item span,
.panel-item small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-item small {
  margin-top: 3px;
  color: rgba(148, 163, 184, 0.8);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 1fr));
  gap: 12px;
}

.panel-groups {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.theme-group {
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  padding: 10px;
  background: rgba(15, 23, 42, 0.26);
}

.theme-group h4 {
  margin: 0 0 10px;
  color: rgba(226, 232, 240, 0.96);
  font-size: 13px;
}

label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: rgba(226, 232, 240, 0.94);
  font-size: 12px;
}

input,
select {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.72);
  color: rgba(248, 250, 252, 0.96);
  padding: 8px 9px;
  outline: none;
}

.asset-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.asset-btn {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  background: rgba(14, 116, 144, 0.28);
  color: rgba(224, 242, 254, 0.96);
  padding: 8px 10px;
  font-size: 12px;
  cursor: pointer;
}

.asset-btn:disabled {
  cursor: default;
  opacity: 0.62;
}

.asset-error {
  margin-top: 10px;
  border: 1px solid rgba(248, 113, 113, 0.28);
  border-radius: 8px;
  background: rgba(127, 29, 29, 0.32);
  color: rgba(254, 202, 202, 0.96);
  padding: 8px 10px;
  font-size: 12px;
}

.color-field {
  gap: 7px;
}

.color-row {
  display: grid;
  grid-template-columns: 44px 1fr;
  gap: 8px;
}

.color-picker {
  width: 44px;
  min-width: 44px;
  height: 36px;
  padding: 3px;
  cursor: pointer;
}

.color-text {
  width: 100%;
}

.palette-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(20px, 1fr));
  gap: 5px;
}

.palette-swatch {
  width: 100%;
  aspect-ratio: 1;
  min-height: 20px;
  border: 1px solid rgba(226, 232, 240, 0.38);
  border-radius: 5px;
  padding: 0;
  cursor: pointer;
}

.palette-swatch.transparent {
  background:
    linear-gradient(45deg, rgba(148, 163, 184, 0.42) 25%, transparent 25%),
    linear-gradient(-45deg, rgba(148, 163, 184, 0.42) 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, rgba(148, 163, 184, 0.42) 75%),
    linear-gradient(-45deg, transparent 75%, rgba(148, 163, 184, 0.42) 75%);
  background-position: 0 0, 0 10px, 10px -10px, -10px 0;
  background-size: 20px 20px;
}

.opacity-row {
  display: grid;
  grid-template-columns: 1fr 42px;
  align-items: center;
  gap: 8px;
}

.opacity-row input {
  padding: 0;
}

.opacity-row span {
  color: rgba(148, 163, 184, 0.86);
  text-align: right;
}

@media (max-width: 900px) {
  .theme-layout,
  .preset-grid,
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
