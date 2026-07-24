<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { CodexSessionSummary } from '../api'

const props = defineProps<{
  sessions: CodexSessionSummary[]
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
  <section class="codex-session-picker">
    <button
      class="codex-session-current"
      type="button"
      :disabled="loading"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span class="codex-session-current-copy">
        <span class="codex-session-kicker">Codex Session</span>
        <strong>{{ currentLabel }}</strong>
      </span>
      <span class="codex-session-chevron" :class="{ open }" aria-hidden="true">›</span>
    </button>

    <div v-if="open" class="codex-session-menu">
      <div class="codex-session-menu-head">
        <span>Resume Session</span>
        <button type="button" :disabled="loading" @click.stop="emit('refresh')">
          {{ loading ? 'Loading…' : 'Refresh' }}
        </button>
      </div>

      <button
        class="codex-session-item codex-session-new"
        :class="{ active: isNewSession }"
        type="button"
        :disabled="loading || isNewSession"
        @click="choose('')"
      >
        <span class="codex-session-item-title">＋ New Session</span>
        <span class="codex-session-item-preview">Start a new Codex thread with empty Memory.</span>
      </button>

      <button
        v-for="session in sessions"
        :key="session.id"
        class="codex-session-item"
        :class="{ active: session.id === activeSessionId && !isNewSession }"
        type="button"
        :disabled="loading || (session.id === activeSessionId && !isNewSession)"
        @click="choose(session.id)"
      >
        <span class="codex-session-item-line">
          <strong>{{ session.title || 'Session' }}</strong>
          <span v-if="session.id === activeSessionId && !isNewSession" class="codex-session-badge">Current</span>
        </span>
        <span class="codex-session-item-preview">{{ session.preview || 'No user message summary.' }}</span>
        <span class="codex-session-item-meta">
          <span v-if="session.source">{{ session.source }}</span>
          <span v-if="session.cwd">· {{ compactPath(session.cwd) }}</span>
          <span v-if="session.updated_at">· {{ formatTime(session.updated_at) }}</span>
        </span>
      </button>

      <p v-if="!sessions.length" class="codex-session-empty">No previous Sessions yet.</p>
    </div>
  </section>
</template>

<style scoped>
.codex-session-picker {
  position: relative;
  z-index: 8;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(2, 6, 23, 0.36);
}

.codex-session-current {
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

.codex-session-current:disabled {
  cursor: wait;
  opacity: 0.7;
}

.codex-session-current-copy {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.codex-session-current-copy strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.codex-session-kicker {
  color: rgba(148, 163, 184, 0.9);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.codex-session-chevron {
  color: rgba(148, 163, 184, 0.9);
  font-size: 20px;
  transform: rotate(90deg);
  transition: transform 0.16s ease;
}

.codex-session-chevron.open {
  transform: rotate(-90deg);
}

.codex-session-menu {
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

.codex-session-menu-head {
  padding: 2px 3px 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: rgba(203, 213, 225, 0.88);
  font-size: 11px;
}

.codex-session-menu-head button {
  color: #93c5fd;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.codex-session-item {
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

.codex-session-item:hover:not(:disabled) {
  border-color: rgba(96, 165, 250, 0.55);
  background: rgba(30, 41, 59, 0.92);
}

.codex-session-item.active {
  border-color: rgba(96, 165, 250, 0.62);
  background: rgba(30, 64, 175, 0.2);
}

.codex-session-item:disabled {
  cursor: default;
  opacity: 0.82;
}

.codex-session-item-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}

.codex-session-item-title {
  font-size: 12px;
  font-weight: 700;
}

.codex-session-item-preview,
.codex-session-item-meta,
.codex-session-empty {
  color: rgba(148, 163, 184, 0.88);
  font-size: 10px;
}

.codex-session-item-preview {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.codex-session-badge {
  padding: 1px 5px;
  color: #bfdbfe;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.34);
  font-size: 9px;
}

.codex-session-empty {
  margin: 4px;
  text-align: center;
}
</style>
