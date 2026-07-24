<script setup lang="ts">
import { nextTick, ref } from 'vue'
import DialogCloseButton from './DialogCloseButton.vue'

defineOptions({
  inheritAttrs: false,
})

withDefaults(
  defineProps<{
    modelValue: string
    rows?: number
    placeholder?: string
    title?: string
    ariaLabel?: string
    disabled?: boolean
    readonly?: boolean
    minHeight?: string
    maxHeight?: string
  }>(),
  {
    rows: 3,
    placeholder: '',
    title: 'Text Editor',
    ariaLabel: 'Text input',
    disabled: false,
    readonly: false,
    minHeight: '78px',
    maxHeight: 'none',
  },
)

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
  (event: 'keydown', value: KeyboardEvent): void
  (event: 'paste', value: ClipboardEvent): void
  (event: 'dragover', value: DragEvent): void
  (event: 'dragleave', value: DragEvent): void
  (event: 'drop', value: DragEvent): void
}>()

const expanded = ref(false)
const expandedTextarea = ref<HTMLTextAreaElement | null>(null)

function updateValue(event: Event) {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
}

async function openEditor() {
  expanded.value = true
  await nextTick()
  expandedTextarea.value?.focus()
}

function closeEditor() {
  expanded.value = false
}
</script>

<template>
  <div
    class="expandable-textarea"
    :style="{
      '--expandable-textarea-min-height': minHeight,
      '--expandable-textarea-max-height': maxHeight,
    }"
  >
    <textarea
      class="expandable-textarea__input"
      :value="modelValue"
      :rows="rows"
      :placeholder="placeholder"
      :aria-label="ariaLabel"
      :disabled="disabled"
      :readonly="readonly"
      @input="updateValue"
      @keydown="emit('keydown', $event)"
      @paste="emit('paste', $event)"
      @dragover="emit('dragover', $event)"
      @dragleave="emit('dragleave', $event)"
      @drop="emit('drop', $event)"
    ></textarea>

    <button
      class="expandable-textarea__expand"
      type="button"
      aria-label="Open large text editor"
      title="Open large text editor"
      :disabled="disabled"
      @click="openEditor"
    >
      <span class="expandable-textarea__expand-icon" aria-hidden="true"></span>
    </button>
  </div>

  <Teleport to="body">
    <div
      v-if="expanded"
      class="expandable-textarea__backdrop"
      role="presentation"
      @click.self="closeEditor"
    >
      <section
        class="expandable-textarea__dialog"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
      >
        <header class="expandable-textarea__header">
          <strong>{{ title }}</strong>
          <DialogCloseButton aria-label="Close large text editor" @click="closeEditor" />
        </header>

        <textarea
          ref="expandedTextarea"
          class="expandable-textarea__editor"
          :value="modelValue"
          :placeholder="placeholder"
          :aria-label="ariaLabel"
          :readonly="readonly"
          @input="updateValue"
          @keydown.esc.prevent.stop="closeEditor"
          @paste="emit('paste', $event)"
          @dragover="emit('dragover', $event)"
          @dragleave="emit('dragleave', $event)"
          @drop="emit('drop', $event)"
        ></textarea>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.expandable-textarea {
  position: relative;
  width: 100%;
  min-width: 0;
}

.expandable-textarea__input {
  display: block;
  width: 100%;
  min-height: var(--expandable-textarea-min-height, 78px);
  max-height: var(--expandable-textarea-max-height, none);
  resize: vertical;
  border: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.22));
  border-radius: 10px;
  outline: none;
  background: var(--theme-panel-node-side-editor-input-background, rgba(15, 23, 42, 0.88));
  color: var(--theme-panel-node-side-editor-input-text, #f8fafc);
  padding: 10px 42px 10px 12px;
  font: inherit;
  font-size: var(--theme-panel-node-side-editor-input-font-size, 13px);
  line-height: 1.4;
  box-sizing: border-box;
}

.expandable-textarea__input:focus {
  border-color: var(--theme-panel-node-side-editor-input-focus-border, rgba(56, 189, 248, 0.7));
}

.expandable-textarea__input:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.expandable-textarea__expand {
  position: absolute;
  top: 8px;
  right: 8px;
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  padding: 0;
  border: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.28));
  border-radius: 6px;
  background: var(--theme-panel-node-side-editor-input-background, rgba(15, 23, 42, 0.94));
  color: var(--theme-panel-node-side-editor-muted-text, #94a3b8);
  cursor: pointer;
}

.expandable-textarea__expand:hover:not(:disabled) {
  border-color: var(--theme-panel-node-side-editor-input-focus-border, rgba(56, 189, 248, 0.7));
  color: var(--theme-panel-node-side-editor-input-text, #f8fafc);
}

.expandable-textarea__expand:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.expandable-textarea__expand-icon {
  width: 11px;
  height: 11px;
  border: 1.5px solid currentColor;
  border-radius: 1px;
  box-sizing: border-box;
}

.expandable-textarea__backdrop {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgb(2 6 23 / 72%);
  backdrop-filter: blur(3px);
}

.expandable-textarea__dialog {
  display: flex;
  width: min(1100px, calc(100vw - 48px));
  height: min(78vh, 800px);
  min-height: 360px;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.28));
  border-radius: 14px;
  background: var(--theme-panel-node-side-editor-background, #111827);
  box-shadow: 0 24px 80px rgb(0 0 0 / 50%);
}

.expandable-textarea__header {
  display: flex;
  min-height: 52px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 14px 10px 18px;
  border-bottom: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.22));
  color: var(--theme-panel-node-side-editor-input-text, #f8fafc);
}

.expandable-textarea__editor {
  min-height: 0;
  flex: 1;
  resize: none;
  border: 0;
  outline: 0;
  background: var(--theme-panel-node-side-editor-input-background, #0f172a);
  color: var(--theme-panel-node-side-editor-input-text, #f8fafc);
  padding: 22px 24px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 18px;
  line-height: 1.6;
  tab-size: 2;
}

@media (max-width: 640px) {
  .expandable-textarea__backdrop {
    padding: 10px;
  }

  .expandable-textarea__dialog {
    width: calc(100vw - 20px);
    height: calc(100vh - 20px);
    min-height: 0;
  }

  .expandable-textarea__editor {
    padding: 16px;
  }
}
</style>
