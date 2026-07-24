<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { runDoubaoSpeechManagement } from '../../doubaoSpeechManagementApi'

const props = defineProps<{ providerId: string }>()

const operations = [
  ['list_speakers', 'List built-in speakers'],
  ['clone_voice', 'Train cloned voice'],
  ['get_voice', 'Query cloned voice'],
  ['upgrade_voice', 'Upgrade cloned voice'],
  ['design_voice', 'Design voice'],
] as const

const templates: Record<string, Record<string, unknown>> = {
  list_speakers: { ResourceIDs: ['seed-tts-2.0'] },
  clone_voice: {
    speaker_id: '',
    audio: { data: '', format: 'wav' },
    text: '',
    language: 0,
    extra_params: { demo_text: '', enable_audio_denoise: false, disable_volume_normalization: false },
  },
  get_voice: { speaker_id: '' },
  upgrade_voice: { speaker_id: '' },
  design_voice: { speaker_id: '', text: '', prompt: { text_prompt: '' } },
}

const operation = ref('list_speakers')
const payloadText = ref('')
const resultText = ref('')
const error = ref('')
const busy = ref(false)
const selectedFileName = ref('')
const indexedSpeakerCount = ref(0)
const selectedLabel = computed(() => operations.find(([value]) => value === operation.value)?.[1] || operation.value)

function resetPayload() {
  payloadText.value = JSON.stringify(templates[operation.value] || {}, null, 2)
  resultText.value = ''
  error.value = ''
  selectedFileName.value = ''
  indexedSpeakerCount.value = 0
}

watch(operation, resetPayload, { immediate: true })

async function attachCloneAudio(file: File | null) {
  selectedFileName.value = file?.name || ''
  if (!file) return
  if (file.size > 10 * 1024 * 1024) {
    error.value = 'Voice-clone audio must not exceed 10 MB.'
    return
  }
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.addEventListener('load', () => resolve(String(reader.result || '')), { once: true })
    reader.addEventListener('error', () => reject(reader.error || new Error('Failed to read audio file.')), { once: true })
    reader.readAsDataURL(file)
  })
  const payload = parsePayload()
  const extension = file.name.split('.').pop()?.toLowerCase() || 'wav'
  payload.audio = { data: dataUrl.slice(dataUrl.indexOf(',') + 1), format: extension }
  payloadText.value = JSON.stringify(payload, null, 2)
}

function parsePayload() {
  let parsed: unknown
  try {
    parsed = JSON.parse(payloadText.value)
  } catch (cause) {
    throw new Error(`Payload is not valid JSON: ${cause instanceof Error ? cause.message : String(cause)}`)
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Payload must be a JSON object.')
  }
  return parsed as Record<string, unknown>
}

async function execute() {
  error.value = ''
  resultText.value = ''
  busy.value = true
  try {
    const response = await runDoubaoSpeechManagement(props.providerId, operation.value, parsePayload())
    resultText.value = JSON.stringify(response.result, null, 2)
    indexedSpeakerCount.value = Number(response.speaker_option_count || 0)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="speech-management">
    <div class="management-head">
      <div>
        <strong>Doubao Speech Management</strong>
        <small>Provider-side voice and vocabulary operations</small>
      </div>
      <button type="button" :disabled="busy" @click="resetPayload">Reset payload</button>
    </div>
    <div class="management-grid">
      <label>
        <span>Operation</span>
        <select v-model="operation" :disabled="busy">
          <option v-for="([value, label]) in operations" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <label v-if="operation === 'clone_voice'">
        <span>Training audio</span>
        <input type="file" accept="audio/*,.wav,.mp3,.ogg,.m4a,.aac,.pcm" :disabled="busy" @change="attachCloneAudio(($event.target as HTMLInputElement).files?.[0] || null)" />
        <small v-if="selectedFileName">{{ selectedFileName }}</small>
      </label>
    </div>
    <label>
      <span>{{ selectedLabel }} payload</span>
      <textarea v-model="payloadText" spellcheck="false" :disabled="busy"></textarea>
    </label>
    <div class="management-actions">
      <button type="button" :disabled="busy || !providerId" @click="execute">{{ busy ? 'Running…' : 'Run operation' }}</button>
      <small>Uses this Provider's X-Api-Key or signed Speech Access Key credentials, as required by the selected operation.</small>
    </div>
    <p v-if="error" class="management-error">{{ error }}</p>
    <p v-if="indexedSpeakerCount" class="management-success">
      Indexed {{ indexedSpeakerCount }} speakers in config/audio_speaker.json.
    </p>
    <label v-if="resultText">
      <span>Result</span>
      <textarea :value="resultText" readonly spellcheck="false"></textarea>
    </label>
  </section>
</template>

<style scoped>
.speech-management { display: flex; flex-direction: column; gap: 10px; padding: 12px; border: 1px solid rgba(56, 189, 248, .24); border-radius: 10px; background: rgba(8, 47, 73, .14); }
.management-head, .management-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.management-head > div { display: flex; flex-direction: column; gap: 3px; }
.management-head small, .management-actions small, label small { color: rgba(148, 163, 184, .92); }
.management-grid { display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); gap: 12px; }
label { display: flex; flex-direction: column; gap: 5px; color: rgba(226, 232, 240, .94); font-size: 12px; }
input, select, textarea { width: 100%; border: 1px solid rgba(148, 163, 184, .24); border-radius: 8px; padding: 8px 9px; color: rgba(226, 232, 240, .96); background: rgba(2, 6, 23, .5); font: inherit; }
textarea { min-height: 150px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.management-error { margin: 0; color: rgba(254, 202, 202, .96); font-size: 12px; overflow-wrap: anywhere; }
.management-success { margin: 0; color: rgba(134, 239, 172, .96); font-size: 12px; }
@media (max-width: 900px) { .management-grid { grid-template-columns: 1fr; } .management-head, .management-actions { align-items: flex-start; flex-direction: column; } }
</style>
