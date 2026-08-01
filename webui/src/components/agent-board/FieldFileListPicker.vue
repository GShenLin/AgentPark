<script setup lang="ts">
import { ref, watch } from 'vue'
import { normalizePathList } from '../../composables/droppedPaths'
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import DialogCloseButton from '../DialogCloseButton.vue'
import FileExplorer from '../FileExplorer.vue'

const props = defineProps<{
  value: unknown
  rootPath: string
  label: string
  resetKey: string
}>()

const emit = defineEmits<{
  'update-value': [value: string[]]
}>()

const open = ref(false)
const selectedPaths = ref<string[]>([])

function openPicker() {
  selectedPaths.value = normalizePathList(props.value)
  open.value = true
}

function closePicker() {
  open.value = false
}

function confirmSelection() {
  emit('update-value', normalizePathList(selectedPaths.value))
  closePicker()
}

function removePath(path: string) {
  emit('update-value', normalizePathList(props.value).filter((item) => item !== path))
}

watch(
  () => props.resetKey,
  () => {
    open.value = false
    selectedPaths.value = []
  },
)
</script>

<template>
  <div class="file-list-field">
    <div v-if="normalizePathList(value).length" class="selected-files">
      <span
        v-for="path in normalizePathList(value)"
        :key="path"
        class="selected-file"
        :title="path"
      >
        <span>{{ path }}</span>
        <DangerButton icon compact :aria-label="`Remove ${path}`" @click.prevent.stop="removePath(path)">×</DangerButton>
      </span>
    </div>
    <ActionButton block @click.prevent.stop="openPicker">
      {{ normalizePathList(value).length ? 'Change files' : 'Select files' }}
    </ActionButton>

    <Teleport to="body">
      <div v-if="open" class="picker-backdrop" @click.self="closePicker">
        <section class="picker-dialog" role="dialog" aria-modal="true" :aria-label="`Select ${label}`">
          <header class="picker-header">
            <div>
              <strong>{{ label }}</strong>
              <span>Select one or more project files.</span>
            </div>
            <DialogCloseButton aria-label="Close file picker" @click="closePicker" />
          </header>
          <div class="picker-tree">
            <FileExplorer
              v-model:selected-paths="selectedPaths"
              :root-path="rootPath"
              :context-menu-enabled="false"
              selectable
            />
          </div>
          <footer class="picker-actions">
            <span>{{ selectedPaths.length }} selected</span>
            <ActionButton compact @click="closePicker">Cancel</ActionButton>
            <ActionButton variant="primary" compact @click="confirmSelection">Confirm</ActionButton>
          </footer>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.file-list-field, .selected-files { display: flex; flex-direction: column; gap: 7px; }
.selected-file { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; border: 1px solid rgba(45, 212, 191, 0.35); border-radius: 8px; background: rgba(13, 148, 136, 0.13); color: #ccfbf1; padding: 3px 3px 3px 8px; text-align: left; }
.selected-file span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.picker-backdrop { position: fixed; inset: 0; z-index: 2600; display: flex; align-items: center; justify-content: center; padding: 20px; background: var(--ui-dialog-backdrop); }
.picker-dialog { width: min(780px, 100%); height: min(76vh, 720px); display: flex; flex-direction: column; border: 1px solid var(--ui-dialog-border); border-radius: var(--ui-dialog-radius); background: var(--ui-dialog-background); color: var(--ui-dialog-text); box-shadow: var(--ui-dialog-shadow); overflow: hidden; }
.picker-header, .picker-actions { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 14px; }
.picker-header { border-bottom: 1px solid rgba(148, 163, 184, 0.18); }
.picker-header > div { display: flex; flex-direction: column; gap: 3px; color: #f8fafc; }
.picker-header span, .picker-actions span { color: rgba(148, 163, 184, 0.92); font-size: 11px; }
.picker-tree { min-height: 0; flex: 1; }
.picker-actions { justify-content: flex-end; border-top: 1px solid rgba(148, 163, 184, 0.18); }
.picker-actions span { margin-right: auto; }
@media (max-width: 760px) {
  .picker-backdrop { align-items: flex-end; padding: 0; }
  .picker-dialog { width: 100%; height: 88vh; border-width: 1px 0 0; border-radius: 0; }
}
</style>
