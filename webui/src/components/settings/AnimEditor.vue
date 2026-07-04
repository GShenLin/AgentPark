<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  createPetAvatar,
  getPetAvatar,
  listPetAvatars,
  savePetAvatarFrame,
  uploadPetAvatarAsset,
  type PetAvatarFrame,
  type PetAvatarSequenceState,
  type PetAvatarState,
  type PetAvatarSummary,
} from '../../api'
import AnimTrackEditor from './AnimTrackEditor.vue'
import PetAvatarRenderer from '../pet-avatar/PetAvatarRenderer.vue'

const emit = defineEmits<{
  error: [message: string]
  status: [message: string]
}>()

const DEFAULT_STATES = ['idle', 'working', 'speaking', 'error', 'sleeping']
const catalogRoot = ref('')
const avatars = ref<PetAvatarSummary[]>([])
const selectedAvatarId = ref('')
const frame = ref<PetAvatarFrame | null>(null)
const savedSnapshot = ref('')
const selectedState = ref('idle')
const newAvatarId = ref('')
const newAvatarName = ref('')
const newStateId = ref('')
const loading = ref(false)
const saving = ref(false)
const uploading = ref(false)
const previewPlaying = ref(false)
const playheadFrame = ref(0)
const resizing = ref<{ index: number; startX: number; startFrames: number } | null>(null)
let previewTimer: number | null = null

const dirty = computed(() => frame.value ? JSON.stringify(frame.value) !== savedSnapshot.value : false)
const availableStates = computed(() => {
  const names = new Set(DEFAULT_STATES)
  for (const state of Object.keys(frame.value?.states || {})) names.add(state)
  return Array.from(names)
})
const activeState = computed<PetAvatarState | null>(() => frame.value?.states[selectedState.value] || null)
const isSequence = computed(() => activeState.value?.type === 'sequence')
const sequenceState = computed(() => activeState.value?.type === 'sequence' ? activeState.value as PetAvatarSequenceState : null)
const timelineFrames = computed(() => sequenceState.value?.frames || [])
const totalFrames = computed(() => timelineFrames.value.reduce((sum, item) => sum + item.holdFrames, 0))

function cloneFrame(value: PetAvatarFrame): PetAvatarFrame {
  return JSON.parse(JSON.stringify(value)) as PetAvatarFrame
}

function setStatus(message: string) {
  emit('status', message)
}

function setError(exc: unknown) {
  emit('error', exc instanceof Error ? exc.message : String(exc || 'AnimEditor failed'))
}

async function loadCatalog(selectFirst = false) {
  const result = await listPetAvatars()
  catalogRoot.value = result.root
  avatars.value = result.avatars
  if (selectFirst && !selectedAvatarId.value) {
    selectedAvatarId.value = result.avatars.find((item) => item.valid)?.id || result.avatars[0]?.id || ''
  }
}

async function loadAvatar(avatarId = selectedAvatarId.value) {
  const safeAvatarId = avatarId.trim()
  if (!safeAvatarId) {
    frame.value = null
    savedSnapshot.value = ''
    return
  }
  loading.value = true
  try {
    const result = await getPetAvatar(safeAvatarId)
    frame.value = cloneFrame(result.avatar)
    savedSnapshot.value = JSON.stringify(result.avatar)
    selectedAvatarId.value = safeAvatarId
    if (!availableStates.value.includes(selectedState.value)) selectedState.value = availableStates.value[0] || 'idle'
    setStatus('Loaded')
  } catch (exc) {
    setError(exc)
  } finally {
    loading.value = false
  }
}

async function createAvatar() {
  const id = newAvatarId.value.trim()
  if (!id) return
  loading.value = true
  try {
    const result = await createPetAvatar({ id, name: newAvatarName.value.trim() || id })
    frame.value = cloneFrame(result.avatar)
    savedSnapshot.value = JSON.stringify(result.avatar)
    selectedAvatarId.value = id
    newAvatarId.value = ''
    newAvatarName.value = ''
    await loadCatalog()
    setStatus('Created')
  } catch (exc) {
    setError(exc)
  } finally {
    loading.value = false
  }
}

function createState() {
  if (!frame.value) return
  const stateId = newStateId.value.trim()
  if (!stateId) return
  frame.value.states[stateId] = { type: 'sequence', loop: true, frames: [] }
  selectedState.value = stateId
  newStateId.value = ''
}

function ensureSequenceState() {
  if (!frame.value) return null
  const current = frame.value.states[selectedState.value]
  if (current?.type === 'sequence') return current
  const nextState: PetAvatarSequenceState = { type: 'sequence', loop: true, frames: [] }
  frame.value.states[selectedState.value] = nextState
  return nextState
}

function setGifState(src: string, url: string) {
  if (!frame.value) return
  frame.value.states[selectedState.value] = { type: 'gif', src, url, loop: true }
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error || new Error('failed to read file'))
    reader.readAsDataURL(file)
  })
}

async function uploadFiles(files: FileList | File[]) {
  if (!frame.value || uploading.value) return
  const list = Array.from(files).filter((file) => /\.(gif|png|webp)$/i.test(file.name))
  if (!list.length) return
  uploading.value = true
  try {
    for (const file of list) {
      const contentBase64 = await readFileAsDataUrl(file)
      const uploaded = await uploadPetAvatarAsset({
        avatar_id: frame.value.id,
        state: selectedState.value,
        filename: file.name,
        content_base64: contentBase64,
      })
      if (uploaded.extension === '.gif') {
        setGifState(uploaded.src, uploaded.url)
      } else {
        const state = ensureSequenceState()
        state?.frames.push({ src: uploaded.src, url: uploaded.url, holdFrames: 6 })
      }
    }
    setStatus('Assets added')
  } catch (exc) {
    setError(exc)
  } finally {
    uploading.value = false
  }
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  if (event.dataTransfer?.files?.length) void uploadFiles(event.dataTransfer.files)
}

function onFileInput(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) void uploadFiles(input.files)
  input.value = ''
}

function removeFrame(index: number) {
  const frames = sequenceState.value?.frames
  if (!frames) return
  frames.splice(index, 1)
}

function updateLoop(value: boolean) {
  const state = activeState.value
  if (state) state.loop = value
}

function startResize(event: PointerEvent, index: number) {
  const item = timelineFrames.value[index]
  if (!item) return
  resizing.value = { index, startX: event.clientX, startFrames: item.holdFrames }
  window.addEventListener('pointermove', onResizeMove)
  window.addEventListener('pointerup', stopResize)
}

function onResizeMove(event: PointerEvent) {
  const state = resizing.value
  if (!state) return
  const item = timelineFrames.value[state.index]
  if (!item) return
  const deltaFrames = Math.round((event.clientX - state.startX) / 12)
  item.holdFrames = Math.max(1, Math.min(600, state.startFrames + deltaFrames))
}

function stopResize() {
  resizing.value = null
  window.removeEventListener('pointermove', onResizeMove)
  window.removeEventListener('pointerup', stopResize)
}

function clampPlayhead(value: number) {
  const frame = Number.isFinite(value) ? value : 0
  return Math.max(0, Math.min(totalFrames.value, frame))
}

function stopPreviewAnimation() {
  if (previewTimer !== null) window.clearTimeout(previewTimer)
  previewTimer = null
}

function stepPreview() {
  const state = sequenceState.value
  if (!previewPlaying.value || !state || totalFrames.value <= 0) {
    stopPreviewAnimation()
    return
  }
  const nextFrame = playheadFrame.value + 1
  if (state.loop) {
    playheadFrame.value = totalFrames.value > 0 ? nextFrame % totalFrames.value : 0
  } else {
    playheadFrame.value = clampPlayhead(nextFrame)
    if (playheadFrame.value >= totalFrames.value) {
      previewPlaying.value = false
      stopPreviewAnimation()
      return
    }
  }
  startPreviewAnimation()
}

function startPreviewAnimation() {
  stopPreviewAnimation()
  if (!previewPlaying.value || !sequenceState.value || totalFrames.value <= 0) return
  const fps = Math.max(1, Math.min(60, frame.value?.fps || 12))
  previewTimer = window.setTimeout(stepPreview, Math.round(1000 / fps))
}

function togglePreview() {
  previewPlaying.value = !previewPlaying.value
  if (previewPlaying.value) {
    if (playheadFrame.value >= totalFrames.value) playheadFrame.value = 0
    startPreviewAnimation()
  } else {
    stopPreviewAnimation()
  }
}

function pausePreview() {
  previewPlaying.value = false
  stopPreviewAnimation()
}

async function saveFrame() {
  if (!frame.value || saving.value) return
  saving.value = true
  try {
    const clean = cloneFrame(frame.value)
    const result = await savePetAvatarFrame(clean.id, clean)
    frame.value = cloneFrame(result.avatar)
    savedSnapshot.value = JSON.stringify(result.avatar)
    await loadCatalog()
    setStatus('Saved')
  } catch (exc) {
    setError(exc)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    await loadCatalog(true)
    await loadAvatar()
  } catch (exc) {
    setError(exc)
  }
})

onBeforeUnmount(stopResize)
onBeforeUnmount(stopPreviewAnimation)

watch(() => [selectedState.value, totalFrames.value], () => {
  playheadFrame.value = clampPlayhead(playheadFrame.value)
  pausePreview()
})
</script>

<template>
  <div class="anim-editor">
    <aside class="anim-sidebar">
      <div class="anim-create">
        <input v-model="newAvatarId" type="text" placeholder="avatar-id" spellcheck="false" />
        <input v-model="newAvatarName" type="text" placeholder="Name" />
        <button type="button" class="settings-btn" :disabled="loading || !newAvatarId.trim()" @click="createAvatar">New</button>
      </div>

      <div class="anim-avatar-list">
        <button
          v-for="avatar in avatars"
          :key="avatar.id"
          type="button"
          class="anim-avatar-row"
          :class="{ active: selectedAvatarId === avatar.id, invalid: !avatar.valid }"
          @click="loadAvatar(avatar.id)"
        >
          <span>{{ avatar.name || avatar.id }}</span>
          <small>{{ avatar.id }}</small>
        </button>
      </div>
      <div class="anim-root">{{ catalogRoot }}</div>
    </aside>

    <section class="anim-main">
      <div class="anim-row anim-top-row">
        <label>
          <span>Avatar</span>
          <input v-if="frame" v-model="frame.name" type="text" />
        </label>
        <label>
          <span>FPS</span>
          <input v-if="frame" v-model.number="frame.fps" type="number" min="1" max="60" />
        </label>
        <button type="button" class="settings-btn" :disabled="loading || !selectedAvatarId" @click="loadAvatar()">Reload</button>
        <button type="button" class="settings-btn primary" :disabled="saving || !dirty || !frame" @click="saveFrame">
          {{ saving ? 'Saving...' : 'Save' }}
        </button>
      </div>

      <div v-if="frame" class="anim-workspace">
        <div class="anim-row">
          <label>
            <span>State</span>
            <select v-model="selectedState">
              <option v-for="state in availableStates" :key="state" :value="state">{{ state }}</option>
            </select>
          </label>
          <label>
            <span>NewState</span>
            <input v-model="newStateId" type="text" placeholder="celebrate" spellcheck="false" />
          </label>
          <button type="button" class="settings-btn" :disabled="!newStateId.trim()" @click="createState">Add</button>
          <label class="anim-check">
            <input type="checkbox" :checked="!!activeState?.loop" :disabled="!activeState" @change="updateLoop(($event.target as HTMLInputElement).checked)" />
            <span>Loop</span>
          </label>
        </div>

        <div class="anim-editor-grid">
          <section class="anim-timeline-panel">
            <div class="anim-timeline-head">
              <span>{{ activeState?.type || 'sequence' }}</span>
              <span>{{ totalFrames }} frames</span>
            </div>
            <div class="anim-drop-track" @dragover.prevent @drop="onDrop">
              <template v-if="activeState?.type === 'gif'">
                <div class="anim-gif-block">
                  <span>{{ activeState.src }}</span>
                  <button type="button" class="settings-btn" @click="frame.states[selectedState] = { type: 'sequence', loop: true, frames: [] }">Sequence</button>
                </div>
              </template>
              <template v-else-if="isSequence">
                <div
                  v-for="(item, index) in timelineFrames"
                  :key="`${item.src}-${index}`"
                  class="anim-frame-block"
                  :style="{ width: `${Math.max(64, item.holdFrames * 12)}px` }"
                >
                  <img :src="item.url" alt="" draggable="false" />
                  <span>{{ item.holdFrames }}</span>
                  <button type="button" title="Remove" @click="removeFrame(index)">x</button>
                  <i class="anim-resize" @pointerdown="startResize($event, index)"></i>
                </div>
              </template>
              <div v-if="!activeState || (isSequence && !timelineFrames.length)" class="anim-empty-track">
                <label>
                  <input type="file" multiple accept=".gif,.png,.webp,image/gif,image/png,image/webp" @change="onFileInput" />
                  <span>{{ uploading ? 'Uploading...' : 'Drop GIF, PNG, or WebP' }}</span>
                </label>
              </div>
            </div>
            <AnimTrackEditor
              v-if="sequenceState"
              v-model:playhead-frame="playheadFrame"
              :state="sequenceState"
              :frames="timelineFrames"
              @pause="pausePreview"
            />
            <div class="anim-track-actions">
              <label class="settings-btn file-btn">
                Add Images
                <input type="file" multiple accept=".gif,.png,.webp,image/gif,image/png,image/webp" @change="onFileInput" />
              </label>
            </div>
          </section>

          <section class="anim-test-panel">
            <div class="anim-preview-wrap">
              <PetAvatarRenderer :avatar="frame" :state="selectedState" :playing="false" :display-frame="playheadFrame" />
            </div>
            <div class="anim-test-actions">
              <button type="button" class="settings-btn primary" :disabled="!activeState" @click="togglePreview">
                {{ previewPlaying ? 'Pause' : 'Play' }}
              </button>
            </div>
          </section>
        </div>
      </div>

      <div v-else class="anim-empty-state">No avatar selected</div>
    </section>
  </div>
</template>

<style scoped src="./AnimEditor.css"></style>
