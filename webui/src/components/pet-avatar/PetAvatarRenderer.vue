<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  getActiveApiBase,
  type PetAvatarColorKeyframe,
  type PetAvatarFrame,
  type PetAvatarState,
  type PetAvatarTransformKeyframe,
} from '../../api'

const props = withDefaults(defineProps<{
  avatar?: PetAvatarFrame | null
  state?: string
  playing?: boolean
  displayMode?: 'fit' | 'natural'
  displayFrame?: number | null
}>(), {
  avatar: null,
  state: 'idle',
  playing: true,
  displayMode: 'fit',
  displayFrame: null,
})

const playheadFrame = ref(0)
let timer: number | null = null

const activeStateId = computed(() => {
  const avatar = props.avatar
  if (!avatar) return ''
  const states = avatar.states || {}
  const requested = String(props.state || '').trim()
  if (requested && states[requested]) return requested
  if (states.idle) return 'idle'
  return Object.keys(states)[0] || ''
})

const activeState = computed<PetAvatarState | null>(() => {
  const avatar = props.avatar
  if (!avatar || !activeStateId.value) return null
  return avatar.states[activeStateId.value] || null
})

const sequenceFrames = computed(() => {
  const state = activeState.value
  return state?.type === 'sequence' ? state.frames : []
})

const totalFrames = computed(() => sequenceFrames.value.reduce((sum, item) => sum + item.holdFrames, 0))

const tracks = computed(() => {
  const state = activeState.value
  return state?.type === 'sequence' ? state.tracks || {} : {}
})

const renderFrame = computed(() => {
  if (typeof props.displayFrame === 'number' && Number.isFinite(props.displayFrame)) {
    return Math.max(0, Math.min(props.displayFrame, Math.max(0, totalFrames.value)))
  }
  return playheadFrame.value
})

const currentSequenceFrame = computed(() => {
  const frames = sequenceFrames.value
  if (!frames.length) return null
  let cursor = Math.max(0, Math.min(renderFrame.value, Math.max(0, totalFrames.value - 0.0001)))
  for (const frame of frames) {
    if (cursor < frame.holdFrames) return frame
    cursor -= frame.holdFrames
  }
  return frames[frames.length - 1] || null
})

const currentImageUrl = computed(() => {
  const state = activeState.value
  if (!state) return ''
  if (state.type === 'gif') return absolutizeAssetUrl(state.url || '')
  return absolutizeAssetUrl(currentSequenceFrame.value?.url || '')
})

const transformValue = computed(() => interpolateTransform(tracks.value.transform || [], renderFrame.value))
const colorValue = computed(() => interpolateColor(tracks.value.color || [], renderFrame.value))

const spriteStyle = computed(() => {
  const transform = transformValue.value
  return {
    transform: `translate(${transform.x}px, ${transform.y}px) rotate(${transform.rotation}deg) scale(${transform.scaleX}, ${transform.scaleY})`,
    opacity: String(colorValue.value.opacity),
  }
})

const tintStyle = computed(() => {
  const imageUrl = currentImageUrl.value
  return {
    backgroundColor: colorValue.value.color,
    maskImage: imageUrl ? `url("${imageUrl}")` : '',
    WebkitMaskImage: imageUrl ? `url("${imageUrl}")` : '',
    opacity: colorValue.value.color.toLowerCase() === '#ffffff' ? '0' : '0.42',
  }
})

function absolutizeAssetUrl(url: string) {
  if (!url) return ''
  if (/^https?:\/\//i.test(url)) return url
  return `${getActiveApiBase()}${url}`
}

function clearTimer() {
  if (timer !== null) window.clearTimeout(timer)
  timer = null
}

function stepAnimation() {
  const state = activeState.value
  const frames = sequenceFrames.value
  const frameCount = totalFrames.value
  if (props.displayFrame !== null || !props.playing || state?.type !== 'sequence' || !frames.length || frameCount <= 0) {
    clearTimer()
    return
  }
  const nextFrame = playheadFrame.value + 1
  if (state.loop) {
    playheadFrame.value = frameCount > 0 ? nextFrame % frameCount : 0
  } else {
    playheadFrame.value = Math.min(nextFrame, frameCount)
    if (playheadFrame.value >= frameCount) {
      clearTimer()
      return
    }
  }
  scheduleAnimation()
}

function scheduleAnimation() {
  clearTimer()
  const state = activeState.value
  if (props.displayFrame !== null || !props.playing || state?.type !== 'sequence' || !sequenceFrames.value.length) return
  const fps = Math.max(1, Math.min(60, props.avatar?.fps || 12))
  timer = window.setTimeout(stepAnimation, Math.round(1000 / fps))
}

function interpolateNumber(frame: number, leftFrame: number, rightFrame: number, leftValue: number, rightValue: number) {
  if (rightFrame === leftFrame) return rightValue
  const ratio = Math.max(0, Math.min(1, (frame - leftFrame) / (rightFrame - leftFrame)))
  return leftValue + (rightValue - leftValue) * ratio
}

function sortedTransformKeyframes(keyframes: PetAvatarTransformKeyframe[]) {
  return [...keyframes].sort((left, right) => left.frame - right.frame)
}

function sortedColorKeyframes(keyframes: PetAvatarColorKeyframe[]) {
  return [...keyframes].sort((left, right) => left.frame - right.frame)
}

function interpolateTransform(keyframes: PetAvatarTransformKeyframe[], frame: number) {
  const sorted = sortedTransformKeyframes(keyframes)
  const base = { x: 0, y: 0, rotation: 0, scaleX: 1, scaleY: 1 }
  if (!sorted.length) return base
  const first = sorted[0]!
  if (frame <= first.frame) return { ...base, ...first }
  for (let index = 1; index < sorted.length; index += 1) {
    const left = sorted[index - 1]!
    const right = sorted[index]!
    if (frame <= right.frame) {
      return {
        x: interpolateNumber(frame, left.frame, right.frame, left.x, right.x),
        y: interpolateNumber(frame, left.frame, right.frame, left.y, right.y),
        rotation: interpolateNumber(frame, left.frame, right.frame, left.rotation, right.rotation),
        scaleX: interpolateNumber(frame, left.frame, right.frame, left.scaleX, right.scaleX),
        scaleY: interpolateNumber(frame, left.frame, right.frame, left.scaleY, right.scaleY),
      }
    }
  }
  const last = sorted[sorted.length - 1]!
  return {
    x: last.x,
    y: last.y,
    rotation: last.rotation,
    scaleX: last.scaleX,
    scaleY: last.scaleY,
  }
}

function hexToRgb(color: string) {
  const value = color.replace('#', '')
  return {
    r: Number.parseInt(value.slice(0, 2), 16),
    g: Number.parseInt(value.slice(2, 4), 16),
    b: Number.parseInt(value.slice(4, 6), 16),
  }
}

function rgbToHex(r: number, g: number, b: number) {
  const toHex = (value: number) => Math.round(Math.max(0, Math.min(255, value))).toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

function interpolateColor(keyframes: PetAvatarColorKeyframe[], frame: number) {
  const sorted = sortedColorKeyframes(keyframes)
  const base = { color: '#ffffff', opacity: 1 }
  if (!sorted.length) return base
  const first = sorted[0]!
  if (frame <= first.frame) return { color: first.color, opacity: first.opacity }
  for (let index = 1; index < sorted.length; index += 1) {
    const left = sorted[index - 1]!
    const right = sorted[index]!
    if (frame <= right.frame) {
      const leftColor = hexToRgb(left.color)
      const rightColor = hexToRgb(right.color)
      return {
        color: rgbToHex(
          interpolateNumber(frame, left.frame, right.frame, leftColor.r, rightColor.r),
          interpolateNumber(frame, left.frame, right.frame, leftColor.g, rightColor.g),
          interpolateNumber(frame, left.frame, right.frame, leftColor.b, rightColor.b),
        ),
        opacity: interpolateNumber(frame, left.frame, right.frame, left.opacity, right.opacity),
      }
    }
  }
  const last = sorted[sorted.length - 1]!
  return {
    color: last.color,
    opacity: last.opacity,
  }
}

watch(() => [props.avatar?.id, activeStateId.value], () => {
  playheadFrame.value = 0
  scheduleAnimation()
}, { immediate: true })

watch(() => props.playing, () => {
  if (props.displayFrame !== null || !props.playing) {
    clearTimer()
  } else {
    scheduleAnimation()
  }
})

watch(() => props.displayFrame, () => {
  if (props.displayFrame !== null) clearTimer()
  else scheduleAnimation()
})

watch(totalFrames, () => {
  if (playheadFrame.value > totalFrames.value) playheadFrame.value = 0
  scheduleAnimation()
})

onBeforeUnmount(clearTimer)
</script>

<template>
  <div class="pet-avatar-renderer" :class="`mode-${displayMode}`">
    <div v-if="currentImageUrl" class="pet-avatar-sprite" :style="spriteStyle">
      <img class="pet-avatar-image" :src="currentImageUrl" alt="" draggable="false" />
      <span class="pet-avatar-tint" :style="tintStyle"></span>
    </div>
    <div v-else class="pet-avatar-empty"></div>
  </div>
</template>

<style scoped>
.pet-avatar-renderer {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
}

.pet-avatar-renderer.mode-natural {
  width: auto;
  height: auto;
}

.pet-avatar-sprite {
  position: relative;
  display: inline-grid;
  place-items: center;
  transform-origin: center;
  will-change: transform, opacity;
}

.pet-avatar-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  image-rendering: auto;
  user-select: none;
  pointer-events: none;
}

.pet-avatar-tint {
  position: absolute;
  inset: 0;
  pointer-events: none;
  mix-blend-mode: multiply;
  mask-repeat: no-repeat;
  mask-position: center;
  mask-size: contain;
  -webkit-mask-repeat: no-repeat;
  -webkit-mask-position: center;
  -webkit-mask-size: contain;
}

.mode-natural .pet-avatar-image {
  display: block;
  width: auto;
  height: auto;
  max-width: 112px;
  max-height: 112px;
}

.pet-avatar-empty {
  width: 88%;
  aspect-ratio: 1;
  background: transparent;
}
</style>
