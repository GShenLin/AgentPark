<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { CliSessionSummary } from '../api'
import ActionButton from './ActionButton.vue'

const props = defineProps<{
  sessions: CliSessionSummary[]
  sessionLabel: string
  activeSessionId: string
  isNewSession: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  select: [sessionId: string]
  refresh: []
}>()

const open = ref(false)

const activeSession = computed(() => (
  props.sessions.find((item) => item.id === props.activeSessionId) || null
))

const currentLabel = computed(() => {
  if (props.isNewSession) return 'New Session'
  if (!activeSession.value) return `Current Session · ${props.activeSessionId.slice(0, 8)}`
  return `Current Session · ${activeSession.value.title || 'Session'}`
})

function formatTime(value: string) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const date = new Date(raw.replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return raw
  return new Intl.DateTimeFormat(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function choose(sessionId: string) {
  if (props.loading) return
  open.value = false
  emit('select', sessionId)
}

function compactPath(value: string) {
  const raw = String(value || '').trim().replace(/\\/g, '/')
  if (!raw) return ''
  const parts = raw.split('/').filter(Boolean)
  return parts.length > 2 ? `…/${parts.slice(-2).join('/')}` : raw
}

watch(
  () => [props.activeSessionId, props.isNewSession],
  () => {
    open.value = false
  },
)
</script>

<template>
  <section class="cli-session-picker">
    <button
      class="cli-session-current"
      type="button"
      :disabled="loading"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span class="cli-session-current-copy">
        <span class="cli-session-kicker">{{ sessionLabel }} Session</span>
        <strong>{{ currentLabel }}</strong>
      </span>
      <span class="cli-session-chevron" :class="{ open }" aria-hidden="true">›</span>
    </button>

    <div v-if="open" class="cli-session-menu">
      <div class="cli-session-menu-head">
        <span>Resume Session</span>
        <ActionButton compact :disabled="loading" @click.stop="emit('refresh')">
          {{ loading ? 'Loading…' : 'Refresh' }}
        </ActionButton>
      </div>

      <button
        class="cli-session-item cli-session-new"
        :class="{ active: isNewSession }"
        type="button"
        :disabled="loading || isNewSession"
        @click="choose('')"
      >
        <span class="cli-session-item-title">＋ New Session</span>
        <span class="cli-session-item-preview">Start a new {{ sessionLabel }} Session with empty Memory.</span>
      </button>

      <button
        v-for="session in sessions"
        :key="session.id"
        class="cli-session-item"
        :class="{ active: session.id === activeSessionId && !isNewSession }"
        type="button"
        :disabled="loading || (session.id === activeSessionId && !isNewSession)"
        @click="choose(session.id)"
      >
        <span class="cli-session-item-line">
          <strong>{{ session.title || 'Session' }}</strong>
          <span v-if="session.id === activeSessionId && !isNewSession" class="cli-session-badge">Current</span>
        </span>
        <span class="cli-session-item-preview">{{ session.preview || 'No user message summary.' }}</span>
        <span class="cli-session-item-meta">
          <span v-if="session.source">{{ session.source }}</span>
          <span v-if="session.cwd">· {{ compactPath(session.cwd) }}</span>
          <span v-if="session.updated_at">· {{ formatTime(session.updated_at) }}</span>
        </span>
      </button>

      <p v-if="!sessions.length" class="cli-session-empty">No previous Sessions yet.</p>
    </div>
  </section>
</template>

<style scoped>
.cli-session-picker {
  position: relative;
  z-index: 8;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(2, 6, 23, 0.36);
}

.cli-session-current {
  width: 100%;
  min-height: 52px;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: inherit;
  text-align: left;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.cli-session-current:disabled {
  cursor: wait;
  opacity: 0.7;
}

.cli-session-current-copy {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.cli-session-current-copy strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.cli-session-kicker {
  color: rgba(148, 163, 184, 0.9);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.cli-session-chevron {
  color: rgba(148, 163, 184, 0.9);
  font-size: 20px;
  transform: rotate(90deg);
  transition: transform 0.16s ease;
}

.cli-session-chevron.open {
  transform: rotate(-90deg);
}

.cli-session-menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 8px;
  right: 8px;
  max-height: min(430px, 60vh);
  overflow-y: auto;
  padding: 8px;
  display: grid;
  gap: 6px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 10px;
  background: rgba(8, 15, 29, 0.98);
  box-shadow: 0 18px 45px rgba(0, 0, 0, 0.42);
}

.cli-session-menu-head {
  padding: 2px 3px 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: rgba(203, 213, 225, 0.88);
  font-size: 11px;
}

.cli-session-menu-head button {
  color: #93c5fd;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.cli-session-item {
  padding: 9px 10px;
  display: grid;
  gap: 4px;
  color: inherit;
  text-align: left;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.72);
  cursor: pointer;
}

.cli-session-item:hover:not(:disabled) {
  border-color: rgba(96, 165, 250, 0.55);
  background: rgba(30, 41, 59, 0.92);
}

.cli-session-item.active {
  border-color: rgba(96, 165, 250, 0.62);
  background: rgba(30, 64, 175, 0.2);
}

.cli-session-item:disabled {
  cursor: default;
  opacity: 0.82;
}

.cli-session-item-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}

.cli-session-item-title {
  font-size: 12px;
  font-weight: 700;
}

.cli-session-item-preview,
.cli-session-item-meta,
.cli-session-empty {
  color: rgba(148, 163, 184, 0.88);
  font-size: 10px;
}

.cli-session-item-preview {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cli-session-badge {
  padding: 1px 5px;
  color: #bfdbfe;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.34);
  font-size: 9px;
}

.cli-session-empty {
  margin: 4px;
  text-align: center;
}
</style>
