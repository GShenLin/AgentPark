<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import ActionButton from '../ActionButton.vue'
import ExpandableTextarea from '../ExpandableTextarea.vue'
import { t } from '../../i18n'
import { AgentBoardKey } from './context'

const props = defineProps<{
  nodeId: string
  note?: string
}>()

const injectedCtx = inject(AgentBoardKey, null)
if (!injectedCtx) throw new Error('AgentBoard context not found')
const ctx = injectedCtx

const draft = ref('')
const saving = ref(false)
const normalizedDraft = computed(() => String(draft.value || '').trim())
const savedNote = computed(() => String(props.note || '').trim())
const dirty = computed(() => normalizedDraft.value !== savedNote.value)

watch(
  () => [props.nodeId, props.note] as const,
  () => {
    draft.value = String(props.note || '')
  },
  { immediate: true },
)

async function save() {
  if (!dirty.value || saving.value) return
  saving.value = true
  try {
    await ctx.setNodeNote(props.nodeId, normalizedDraft.value)
    draft.value = normalizedDraft.value
  } finally {
    saving.value = false
  }
}

function reset() {
  draft.value = String(props.note || '')
}

function onKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault()
    void save()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    reset()
  }
}
</script>

<template>
  <div class="node-note-field">
    <div class="node-note-label">{{ t('board.note') }}</div>
    <ExpandableTextarea
      v-model="draft"
      :rows="3"
      :title="t('board.note')"
      :aria-label="t('board.note')"
      :placeholder="t('board.notePlaceholder')"
      @keydown="onKeydown"
    />
    <div class="node-note-footer">
      <span class="node-note-hint">{{ t('board.noteHint') }}</span>
      <ActionButton compact :disabled="!dirty || saving" @click="save">
        {{ saving ? t('common.saving') : t('board.saveNote') }}
      </ActionButton>
    </div>
  </div>
</template>

<style scoped>
.node-note-field {
  display: grid;
  gap: 8px;
  margin-bottom: 12px;
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.4);
}

.node-note-label {
  color: rgba(226, 232, 240, 0.96);
  font-size: 13px;
  font-weight: 700;
}

.node-note-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.node-note-hint {
  min-width: 0;
  color: rgba(148, 163, 184, 0.88);
  font-size: 11px;
  line-height: 1.4;
}
</style>
