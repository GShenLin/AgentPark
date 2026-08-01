<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import {
  type PetAvatarColorKeyframe,
  type PetAvatarSequenceFrame,
  type PetAvatarSequenceState,
  type PetAvatarTransformKeyframe,
} from '../../api'
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import FormTextInput from '../FormTextInput.vue'

const props = defineProps<{
  state: PetAvatarSequenceState
  frames: PetAvatarSequenceFrame[]
  playheadFrame: number
}>()

const emit = defineEmits<{
  'update:playheadFrame': [frame: number]
  pause: []
}>()

const selected = ref<{ track: 'transform' | 'color'; index: number } | null>(null)
const draggingKey = ref<{
  track: 'transform' | 'color'
  key: PetAvatarTransformKeyframe | PetAvatarColorKeyframe
  rail: HTMLElement
  pointerOffsetX: number
} | null>(null)
const draggingPlayhead = ref<HTMLElement | null>(null)

const totalFrames = computed(() => props.frames.reduce((sum, item) => sum + item.holdFrames, 0))
const trackWidth = computed(() => props.frames.reduce((sum, item) => sum + Math.max(64, item.holdFrames * 12), 0))
const transformKeys = computed(() => props.state.tracks?.transform || [])
const colorKeys = computed(() => props.state.tracks?.color || [])
const selectedTransformKey = computed(() => selected.value?.track === 'transform' ? transformKeys.value[selected.value.index] || null : null)
const selectedColorKey = computed(() => selected.value?.track === 'color' ? colorKeys.value[selected.value.index] || null : null)
const playheadMarkerStyle = computed(() => markerStyle(props.playheadFrame))
const roundedPlayhead = computed(() => clampFrame(props.playheadFrame))

function ensureTracks() {
  if (!props.state.tracks) props.state.tracks = {}
  return props.state.tracks
}

function ensureTransformTrack() {
  const tracks = ensureTracks()
  if (!tracks.transform) tracks.transform = []
  return tracks.transform
}

function ensureColorTrack() {
  const tracks = ensureTracks()
  if (!tracks.color) tracks.color = []
  return tracks.color
}

function clampFrame(value: number) {
  const frame = Number.isFinite(value) ? Math.round(value) : 0
  return Math.max(0, Math.min(totalFrames.value, frame))
}

function positionForFrame(frame: number) {
  if (totalFrames.value <= 0) return 0
  return (clampFrame(frame) / totalFrames.value) * 100
}

function markerStyle(frame: number) {
  return { left: `${positionForFrame(frame)}%` }
}

function localXFromClientX(clientX: number, rail: HTMLElement) {
  const rect = rail.getBoundingClientRect()
  if (rect.width <= 0) return 0
  return Math.max(0, Math.min(rect.width, clientX - rect.left))
}

function frameFromRailX(x: number, rail: HTMLElement) {
  const rect = rail.getBoundingClientRect()
  if (rect.width <= 0 || totalFrames.value <= 0) return 0
  return clampFrame((Math.max(0, Math.min(rect.width, x)) / rect.width) * totalFrames.value)
}

function frameFromClientX(clientX: number, rail: HTMLElement) {
  return frameFromRailX(localXFromClientX(clientX, rail), rail)
}

function sortTransformKeys() {
  const key = selectedTransformKey.value
  const sorted = transformKeys.value.sort((left, right) => left.frame - right.frame)
  if (key) selected.value = { track: 'transform', index: sorted.indexOf(key) }
}

function sortColorKeys() {
  const key = selectedColorKey.value
  const sorted = colorKeys.value.sort((left, right) => left.frame - right.frame)
  if (key) selected.value = { track: 'color', index: sorted.indexOf(key) }
}

function frameExists(track: 'transform' | 'color', frame: number, ignoredKey?: PetAvatarTransformKeyframe | PetAvatarColorKeyframe) {
  const keys = track === 'transform' ? transformKeys.value : colorKeys.value
  return keys.some((item) => item !== ignoredKey && item.frame === clampFrame(frame))
}

function addTransformKey() {
  const frame = roundedPlayhead.value
  const keys = ensureTransformTrack()
  const existing = keys.findIndex((item) => item.frame === frame)
  if (existing >= 0) {
    selected.value = { track: 'transform', index: existing }
    return
  }
  const key: PetAvatarTransformKeyframe = { frame, x: 0, y: 0, rotation: 0, scaleX: 1, scaleY: 1 }
  keys.push(key)
  keys.sort((left, right) => left.frame - right.frame)
  selected.value = { track: 'transform', index: keys.indexOf(key) }
}

function addColorKey() {
  const frame = roundedPlayhead.value
  const keys = ensureColorTrack()
  const existing = keys.findIndex((item) => item.frame === frame)
  if (existing >= 0) {
    selected.value = { track: 'color', index: existing }
    return
  }
  const key: PetAvatarColorKeyframe = { frame, color: '#ffffff', opacity: 1 }
  keys.push(key)
  keys.sort((left, right) => left.frame - right.frame)
  selected.value = { track: 'color', index: keys.indexOf(key) }
}

function selectKey(track: 'transform' | 'color', index: number) {
  selected.value = { track, index }
}

function setPlayhead(frame: number) {
  emit('update:playheadFrame', clampFrame(frame))
}

function startPlayheadDrag(event: PointerEvent) {
  event.preventDefault()
  const rail = event.currentTarget as HTMLElement
  draggingPlayhead.value = rail
  emit('pause')
  setPlayhead(frameFromClientX(event.clientX, rail))
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', stopDrag)
}

function startKeyDrag(
  event: PointerEvent,
  track: 'transform' | 'color',
  key: PetAvatarTransformKeyframe | PetAvatarColorKeyframe,
  index: number,
) {
  event.preventDefault()
  event.stopPropagation()
  const rail = (event.currentTarget as HTMLElement).closest('.anim-key-rail') as HTMLElement | null
  if (!rail) return
  const pointerOffsetX = localXFromClientX(event.clientX, rail) - (positionForFrame(key.frame) / 100) * rail.getBoundingClientRect().width
  draggingKey.value = { track, key, rail, pointerOffsetX }
  selected.value = { track, index }
  emit('pause')
  setPlayhead(key.frame)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', stopDrag)
}

function moveKey(track: 'transform' | 'color', key: PetAvatarTransformKeyframe | PetAvatarColorKeyframe, frame: number) {
  const nextFrame = clampFrame(frame)
  if (frameExists(track, nextFrame, key)) return
  key.frame = nextFrame
  if (track === 'transform') {
    const sorted = transformKeys.value.sort((left, right) => left.frame - right.frame)
    selected.value = { track, index: sorted.indexOf(key as PetAvatarTransformKeyframe) }
  } else {
    const sorted = colorKeys.value.sort((left, right) => left.frame - right.frame)
    selected.value = { track, index: sorted.indexOf(key as PetAvatarColorKeyframe) }
  }
  setPlayhead(nextFrame)
}

function onPointerMove(event: PointerEvent) {
  if (draggingPlayhead.value) {
    setPlayhead(frameFromClientX(event.clientX, draggingPlayhead.value))
    return
  }
  if (draggingKey.value) {
    const localX = localXFromClientX(event.clientX, draggingKey.value.rail) - draggingKey.value.pointerOffsetX
    const frame = frameFromRailX(localX, draggingKey.value.rail)
    moveKey(draggingKey.value.track, draggingKey.value.key, frame)
  }
}

function stopDrag() {
  draggingPlayhead.value = null
  draggingKey.value = null
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', stopDrag)
}

function deleteSelectedKey() {
  if (!selected.value) return
  const keys = selected.value.track === 'transform' ? transformKeys.value : colorKeys.value
  keys.splice(selected.value.index, 1)
  selected.value = null
}

function normalizeSelectedFrame() {
  if (selectedTransformKey.value) {
    selectedTransformKey.value.frame = clampFrame(selectedTransformKey.value.frame)
    sortTransformKeys()
  }
  if (selectedColorKey.value) {
    selectedColorKey.value.frame = clampFrame(selectedColorKey.value.frame)
    sortColorKeys()
  }
}

function updateTransformField(field: keyof PetAvatarTransformKeyframe, value: string) {
  const key = selectedTransformKey.value
  if (!key) return
  key[field] = Number(value)
}

function updateColorFrame(value: string) {
  const key = selectedColorKey.value
  if (key) key.frame = Number(value)
}

function updateColorOpacity(value: string) {
  const key = selectedColorKey.value
  if (key) key.opacity = Number(value)
}

onBeforeUnmount(stopDrag)
</script>

<template>
  <div class="anim-track-editor">
    <div class="anim-time-track">
      <div class="anim-time-label">
        <span>Timeline</span>
        <strong>{{ roundedPlayhead }}</strong>
      </div>
      <div class="anim-key-rail-wrap">
        <div class="anim-time-rail" :style="{ width: `${trackWidth}px` }" @pointerdown="startPlayheadDrag">
          <span class="anim-playhead" :style="playheadMarkerStyle"></span>
        </div>
      </div>
    </div>

    <div class="anim-key-track">
      <div class="anim-key-track-label">
        <span>Transform</span>
        <span class="anim-key-frame-readout">{{ roundedPlayhead }}</span>
        <ActionButton compact :disabled="totalFrames <= 0 || frameExists('transform', roundedPlayhead)" @click="addTransformKey">Add</ActionButton>
      </div>
      <div class="anim-key-rail-wrap">
        <div class="anim-key-rail" :style="{ width: `${trackWidth}px` }" @pointerdown="startPlayheadDrag">
          <span class="anim-playhead in-track" :style="playheadMarkerStyle"></span>
          <button
            v-for="(key, index) in transformKeys"
            :key="`transform-${key.frame}-${index}`"
            type="button"
            class="anim-key-marker transform"
            :class="{ active: selected?.track === 'transform' && selected.index === index }"
            :style="markerStyle(key.frame)"
            :title="`Transform ${key.frame}`"
            @click="selectKey('transform', index)"
            @pointerdown="startKeyDrag($event, 'transform', key, index)"
          ></button>
        </div>
      </div>
    </div>

    <div class="anim-key-track">
      <div class="anim-key-track-label">
        <span>Color</span>
        <span class="anim-key-frame-readout">{{ roundedPlayhead }}</span>
        <ActionButton compact :disabled="totalFrames <= 0 || frameExists('color', roundedPlayhead)" @click="addColorKey">Add</ActionButton>
      </div>
      <div class="anim-key-rail-wrap">
        <div class="anim-key-rail" :style="{ width: `${trackWidth}px` }" @pointerdown="startPlayheadDrag">
          <span class="anim-playhead in-track" :style="playheadMarkerStyle"></span>
          <button
            v-for="(key, index) in colorKeys"
            :key="`color-${key.frame}-${index}`"
            type="button"
            class="anim-key-marker color"
            :class="{ active: selected?.track === 'color' && selected.index === index }"
            :style="markerStyle(key.frame)"
            :title="`Color ${key.frame}`"
            @click="selectKey('color', index)"
            @pointerdown="startKeyDrag($event, 'color', key, index)"
          ></button>
        </div>
      </div>
    </div>

    <div v-if="selectedTransformKey" class="anim-key-controls">
      <label><span>Frame</span><FormTextInput :model-value="selectedTransformKey.frame" compact type="number" min="0" :max="totalFrames" @update:model-value="updateTransformField('frame', $event)" @change="normalizeSelectedFrame" /></label>
      <label><span>X</span><FormTextInput :model-value="selectedTransformKey.x" compact type="number" step="1" @update:model-value="updateTransformField('x', $event)" /></label>
      <label><span>Y</span><FormTextInput :model-value="selectedTransformKey.y" compact type="number" step="1" @update:model-value="updateTransformField('y', $event)" /></label>
      <label><span>Rotate</span><FormTextInput :model-value="selectedTransformKey.rotation" compact type="number" step="1" @update:model-value="updateTransformField('rotation', $event)" /></label>
      <label><span>ScaleX</span><FormTextInput :model-value="selectedTransformKey.scaleX" compact type="number" min="0.01" step="0.05" @update:model-value="updateTransformField('scaleX', $event)" /></label>
      <label><span>ScaleY</span><FormTextInput :model-value="selectedTransformKey.scaleY" compact type="number" min="0.01" step="0.05" @update:model-value="updateTransformField('scaleY', $event)" /></label>
      <DangerButton @click="deleteSelectedKey">Delete</DangerButton>
    </div>

    <div v-if="selectedColorKey" class="anim-key-controls">
      <label><span>Frame</span><FormTextInput :model-value="selectedColorKey.frame" compact type="number" min="0" :max="totalFrames" @update:model-value="updateColorFrame" @change="normalizeSelectedFrame" /></label>
      <label><span>Color</span><input v-model="selectedColorKey.color" type="color" /></label>
      <label><span>Opacity</span><FormTextInput :model-value="selectedColorKey.opacity" compact type="number" min="0" max="1" step="0.05" @update:model-value="updateColorOpacity" /></label>
      <DangerButton @click="deleteSelectedKey">Delete</DangerButton>
    </div>
  </div>
</template>

<style scoped src="./AnimTrackEditor.css"></style>
