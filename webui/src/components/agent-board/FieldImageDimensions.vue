<script setup lang="ts">
import { computed, ref, watch } from 'vue'

type FieldOption = { value: string; label: string }

const props = defineProps<{
  value: unknown
  aspectRatioValue: unknown
  fieldSchema: Record<string, unknown>
  resetKey: string
}>()

const emit = defineEmits<{
  'update-value': [value: string]
  'update-aspect-ratio': [value: string]
}>()

const CUSTOM_TIER = 'custom'
const selectedTier = ref(CUSTOM_TIER)
const selectedRatio = ref('')
const width = ref(1024)
const height = ref(1024)
const linked = ref(true)
const validationMessage = ref('')
const lastEmittedValue = ref('')

const tierOptions = computed(() => normalizeOptions(props.fieldSchema?.options))
const ratioOptions = computed(() => normalizeOptions(props.fieldSchema?.aspect_ratios))
const minPixels = computed(() => positiveInteger(props.fieldSchema?.min_pixels))
const maxPixels = computed(() => positiveInteger(props.fieldSchema?.max_pixels))
const aspectRatioField = computed(() => String(props.fieldSchema?.aspect_ratio_field ?? '').trim())
const customDimensionsSupported = computed(() => props.fieldSchema?.custom_dimensions_supported !== false)
const pixelCount = computed(() => width.value * height.value)

function normalizeOptions(value: unknown): FieldOption[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return null
      const raw = item as Record<string, unknown>
      const optionValue = String(raw.value ?? '').trim()
      if (!optionValue) return null
      return { value: optionValue, label: String(raw.label ?? optionValue) }
    })
    .filter((item): item is FieldOption => item != null)
}

function positiveInteger(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function tierBase(value: string): number | null {
  const match = /^(\d+)K$/i.exec(String(value || '').trim())
  return match ? Number(match[1]) * 1024 : null
}

function parseDimensions(value: unknown): { width: number; height: number } | null {
  const match = /^(\d+)[xX](\d+)$/.exec(String(value ?? '').trim())
  if (!match) return null
  const parsedWidth = Number(match[1])
  const parsedHeight = Number(match[2])
  if (!Number.isInteger(parsedWidth) || !Number.isInteger(parsedHeight) || parsedWidth <= 0 || parsedHeight <= 0) return null
  return { width: parsedWidth, height: parsedHeight }
}

function dimensionsForTier(tier: string, ratio: string): { width: number; height: number } | null {
  const base = tierBase(tier)
  if (!base) return null
  if (!ratio) return { width: base, height: base }
  const [ratioWidth, ratioHeight] = ratio.split(':').map(Number)
  if (!ratioWidth || !ratioHeight) return null
  const area = base * base
  return {
    width: Math.max(1, Math.round(Math.sqrt(area * ratioWidth / ratioHeight))),
    height: Math.max(1, Math.round(Math.sqrt(area * ratioHeight / ratioWidth))),
  }
}

function currentRatio(): number {
  const [ratioWidth, ratioHeight] = selectedRatio.value.split(':').map(Number)
  if (ratioWidth && ratioHeight) return ratioWidth / ratioHeight
  return width.value > 0 && height.value > 0 ? width.value / height.value : 1
}

function validateDimensions(nextWidth: number, nextHeight: number): string {
  if (!Number.isInteger(nextWidth) || !Number.isInteger(nextHeight) || nextWidth <= 0 || nextHeight <= 0) {
    return 'Width and height must be positive integers.'
  }
  const pixels = nextWidth * nextHeight
  if (minPixels.value != null && pixels < minPixels.value) {
    return `At least ${minPixels.value.toLocaleString()} pixels are required.`
  }
  if (maxPixels.value != null && pixels > maxPixels.value) {
    return `At most ${maxPixels.value.toLocaleString()} pixels are allowed.`
  }
  const ratio = nextWidth / nextHeight
  if (ratio < 1 / 16 || ratio > 16) return 'Aspect ratio must stay between 1:16 and 16:1.'
  return ''
}

function emitDimensions(value: string) {
  lastEmittedValue.value = value
  emit('update-value', value)
}

function emitAspectRatio(value: string) {
  if (aspectRatioField.value) emit('update-aspect-ratio', value)
}

function applyExactDimensions(nextWidth: number, nextHeight: number) {
  width.value = nextWidth
  height.value = nextHeight
  validationMessage.value = validateDimensions(nextWidth, nextHeight)
  if (!validationMessage.value) emitDimensions(`${nextWidth}x${nextHeight}`)
}

function selectTier(tier: string) {
  const dimensions = dimensionsForTier(tier, selectedRatio.value)
  if (!dimensions) return
  selectedTier.value = tier
  width.value = dimensions.width
  height.value = dimensions.height
  validationMessage.value = validateDimensions(dimensions.width, dimensions.height)
  if (!validationMessage.value) {
    emitDimensions(selectedRatio.value && !aspectRatioField.value ? `${dimensions.width}x${dimensions.height}` : tier)
  }
}

function selectRatio(ratio: string) {
  selectedRatio.value = ratio
  emitAspectRatio(ratio)
  const tier = selectedTier.value
  if (tier !== CUSTOM_TIER) {
    selectTier(tier)
    return
  }
  if (!ratio) {
    applyExactDimensions(width.value, height.value)
    return
  }
  const area = Math.max(1, pixelCount.value)
  const [ratioWidth, ratioHeight] = ratio.split(':').map(Number)
  if (!ratioWidth || !ratioHeight) return
  applyExactDimensions(
    Math.max(1, Math.round(Math.sqrt(area * ratioWidth / ratioHeight))),
    Math.max(1, Math.round(Math.sqrt(area * ratioHeight / ratioWidth))),
  )
}

function updateWidth(event: Event) {
  if (!customDimensionsSupported.value) return
  const nextWidth = Number((event.target as HTMLInputElement).value)
  selectedTier.value = CUSTOM_TIER
  const nextHeight = linked.value ? Math.max(1, Math.round(nextWidth / currentRatio())) : height.value
  applyExactDimensions(nextWidth, nextHeight)
}

function updateHeight(event: Event) {
  if (!customDimensionsSupported.value) return
  const nextHeight = Number((event.target as HTMLInputElement).value)
  selectedTier.value = CUSTOM_TIER
  const nextWidth = linked.value ? Math.max(1, Math.round(nextHeight * currentRatio())) : width.value
  applyExactDimensions(nextWidth, nextHeight)
}

function syncFromValue(value: unknown) {
  const normalized = String(value ?? '').trim()
  if (normalized && normalized === lastEmittedValue.value) return
  lastEmittedValue.value = ''
  selectedRatio.value = aspectRatioField.value ? String(props.aspectRatioValue ?? '').trim() : ''
  validationMessage.value = ''

  const tier = tierOptions.value.find((item) => item.value.toUpperCase() === normalized.toUpperCase())
  if (tier) {
    selectedTier.value = tier.value
    const dimensions = dimensionsForTier(tier.value, '')
    if (dimensions) {
      width.value = dimensions.width
      height.value = dimensions.height
    }
    return
  }

  const dimensions = parseDimensions(normalized)
  selectedTier.value = CUSTOM_TIER
  if (dimensions) {
    width.value = dimensions.width
    height.value = dimensions.height
    validationMessage.value = validateDimensions(dimensions.width, dimensions.height)
    return
  }

  const fallback = tierOptions.value[0]
  if (fallback) {
    selectedTier.value = fallback.value
    const fallbackDimensions = dimensionsForTier(fallback.value, selectedRatio.value)
    if (fallbackDimensions) {
      width.value = fallbackDimensions.width
      height.value = fallbackDimensions.height
    }
  }
}

watch(
  () => [props.value, props.aspectRatioValue, props.resetKey, props.fieldSchema] as const,
  ([value]) => syncFromValue(value),
  { immediate: true, deep: true },
)
</script>

<template>
  <div class="image-dimensions">
    <div class="dimension-section-label">Aspect ratio</div>
    <div class="ratio-grid">
      <button
        type="button"
        class="ratio-option"
        :class="{ active: selectedRatio === '' }"
        aria-label="Automatic aspect ratio"
        @click.prevent.stop="selectRatio('')"
      >
        <span class="ratio-icon ratio-auto">⌗</span>
        <span>Auto</span>
      </button>
      <button
        v-for="option in ratioOptions"
        :key="option.value"
        type="button"
        class="ratio-option"
        :class="{ active: selectedRatio === option.value }"
        :aria-label="`Aspect ratio ${option.label}`"
        @click.prevent.stop="selectRatio(option.value)"
      >
        <span class="ratio-icon" :style="{ aspectRatio: option.value.replace(':', ' / ') }"></span>
        <span>{{ option.label }}</span>
      </button>
    </div>

    <div class="dimension-section-label">Resolution</div>
    <div class="tier-grid">
      <button
        v-for="option in tierOptions"
        :key="option.value"
        type="button"
        class="tier-option"
        :class="{ active: selectedTier === option.value }"
        @click.prevent.stop="selectTier(option.value)"
      >
        {{ option.label }}
      </button>
      <span v-if="selectedTier === CUSTOM_TIER" class="tier-option active custom-tier">Custom</span>
    </div>

    <div class="dimension-section-label">Size</div>
    <div class="size-row">
      <label class="size-input">
        <span>W</span>
        <input
          type="number"
          min="1"
          step="1"
          :value="width"
          :disabled="!customDimensionsSupported"
          aria-label="Image width"
          @blur="updateWidth"
          @keydown.enter.prevent="updateWidth"
        />
      </label>
      <button
        type="button"
        class="link-button"
        :class="{ active: linked }"
        :aria-label="linked ? 'Unlock aspect ratio' : 'Lock aspect ratio'"
        @click.prevent.stop="linked = !linked"
      >
        {{ linked ? '↔' : '×' }}
      </button>
      <label class="size-input">
        <span>H</span>
        <input
          type="number"
          min="1"
          step="1"
          :value="height"
          :disabled="!customDimensionsSupported"
          aria-label="Image height"
          @blur="updateHeight"
          @keydown.enter.prevent="updateHeight"
        />
      </label>
    </div>
    <div class="size-meta">
      <span v-if="validationMessage" class="dimension-error">{{ validationMessage }}</span>
      <span v-else-if="customDimensionsSupported">{{ pixelCount.toLocaleString() }} pixels</span>
      <span v-else>Dimensions are derived from resolution and aspect ratio.</span>
    </div>
  </div>
</template>

<style scoped>
.image-dimensions { display: flex; flex-direction: column; gap: 9px; }
.dimension-section-label { color: rgba(148, 163, 184, 0.92); font-size: 11px; }
.ratio-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 5px; padding: 6px; border-radius: 12px; background: rgba(15, 23, 42, 0.48); }
.ratio-option, .tier-option, .link-button { border: 1px solid transparent; color: rgba(226, 232, 240, 0.9); background: transparent; cursor: pointer; }
.ratio-option { min-height: 48px; border-radius: 9px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; font-size: 11px; }
.ratio-option:hover, .tier-option:hover, .link-button:hover { background: rgba(51, 65, 85, 0.62); }
.ratio-option.active, .tier-option.active { border-color: rgba(94, 234, 212, 0.38); background: rgba(15, 118, 110, 0.18); color: #f8fafc; }
.ratio-icon { display: block; width: 19px; max-height: 15px; border: 2px solid currentColor; border-radius: 3px; }
.ratio-auto { width: auto; border: 0; font-size: 17px; line-height: 15px; }
.tier-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(58px, 1fr)); gap: 6px; }
.tier-option { min-height: 38px; border-radius: 9px; background: rgba(15, 23, 42, 0.66); }
.custom-tier { display: flex; align-items: center; justify-content: center; font-size: 11px; }
.size-row { display: grid; grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr); gap: 5px; align-items: center; }
.size-input { min-width: 0; display: flex; align-items: center; gap: 6px; border-radius: 9px; padding: 8px; background: rgba(15, 23, 42, 0.66); color: rgba(148, 163, 184, 0.95); font-size: 11px; }
.size-input input { min-width: 0; width: 100%; border: 0; outline: none; background: transparent; color: #f8fafc; text-align: right; font: inherit; }
.size-input input:disabled { color: rgba(203, 213, 225, 0.72); cursor: not-allowed; }
.link-button { width: 28px; height: 28px; padding: 0; border-radius: 50%; color: rgba(148, 163, 184, 0.8); }
.link-button.active { color: #5eead4; }
.size-meta { min-height: 15px; color: rgba(148, 163, 184, 0.76); font-size: 10px; text-align: right; }
.dimension-error { color: #fca5a5; }
@media (max-width: 420px) {
  .ratio-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .size-row { grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr); }
}
</style>
