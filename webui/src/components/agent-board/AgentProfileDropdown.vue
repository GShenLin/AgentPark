<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { AgentProfile } from '../../api'

const props = defineProps<{
  profiles: AgentProfile[]
  loading: boolean
  deletingProfileId?: string
}>()

const emit = defineEmits<{
  (event: 'select', profileId: string): void
  (event: 'delete', profileId: string): void
}>()

const menuOpen = ref(false)
const rootEl = ref<HTMLElement | null>(null)

const triggerLabel = computed(() => {
  if (props.loading) return 'Loading...'
  return 'Profile'
})

const disabled = computed(() => props.loading || props.profiles.length === 0)

function closeMenu() {
  menuOpen.value = false
}

function toggleMenu() {
  if (disabled.value) return
  menuOpen.value = !menuOpen.value
}

function chooseProfile(profileId: string) {
  const safeProfileId = String(profileId || '').trim()
  if (!safeProfileId) return
  closeMenu()
  emit('select', safeProfileId)
}

function deleteProfile(profileId: string) {
  const safeProfileId = String(profileId || '').trim()
  if (!safeProfileId || props.deletingProfileId) return
  emit('delete', safeProfileId)
}

function onDocumentPointerDown(event: PointerEvent) {
  const root = rootEl.value
  if (!root || root.contains(event.target as Node | null)) return
  closeMenu()
}

watch(menuOpen, (open) => {
  if (open) {
    document.addEventListener('pointerdown', onDocumentPointerDown)
  } else {
    document.removeEventListener('pointerdown', onDocumentPointerDown)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
})
</script>

<template>
  <div ref="rootEl" class="profile-dropdown">
    <button
      class="profile-trigger"
      type="button"
      :disabled="disabled"
      :aria-expanded="menuOpen"
      @click="toggleMenu"
    >
      <span class="profile-trigger-text">{{ triggerLabel }}</span>
      <span class="profile-trigger-caret">v</span>
    </button>

    <div v-if="menuOpen" class="profile-menu" @pointerdown.stop>
      <div
        v-for="profile in profiles"
        :key="profile.id"
        class="profile-option"
      >
        <button
          class="profile-option-main"
          type="button"
          :disabled="deletingProfileId === profile.id"
          @click="chooseProfile(profile.id)"
        >
          <span class="profile-option-name">{{ profile.name || profile.id }}</span>
        </button>
        <button
          class="profile-delete"
          type="button"
          :disabled="Boolean(deletingProfileId)"
          :title="`Delete ${profile.name || profile.id}`"
          @click="deleteProfile(profile.id)"
        >
          {{ deletingProfileId === profile.id ? '...' : 'X' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.profile-dropdown {
  position: relative;
  flex: 0 0 116px;
  width: 116px;
}

.profile-trigger {
  width: 100%;
  min-height: 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.72);
  color: rgba(226, 232, 240, 0.96);
  padding: 6px 8px;
  font-size: 11px;
  line-height: 1.2;
}

.profile-trigger:focus {
  outline: none;
  border-color: rgba(56, 189, 248, 0.7);
}

.profile-trigger:disabled {
  opacity: 0.62;
  cursor: not-allowed;
}

.profile-trigger-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-trigger-caret {
  color: rgba(148, 163, 184, 0.9);
  font-size: 10px;
}

.profile-menu {
  position: absolute;
  z-index: 3;
  top: calc(100% + 6px);
  right: 0;
  width: 220px;
  max-height: 240px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px;
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 10px;
  background: rgba(2, 6, 23, 0.98);
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.44);
}

.profile-option {
  width: 100%;
  min-height: 30px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: rgba(226, 232, 240, 0.95);
  padding: 4px 4px 4px 8px;
  text-align: left;
}

.profile-option:hover {
  border-color: rgba(56, 189, 248, 0.42);
  background: rgba(14, 116, 144, 0.18);
}

.profile-option-main {
  min-width: 0;
  flex: 1;
  border: 0;
  background: transparent;
  color: inherit;
  padding: 0;
  text-align: left;
}

.profile-option-main:disabled {
  opacity: 0.68;
  cursor: wait;
}

.profile-option-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
}

.profile-delete {
  flex: 0 0 22px;
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(248, 113, 113, 0.35);
  border-radius: 6px;
  background: rgba(127, 29, 29, 0.28);
  color: rgba(254, 202, 202, 0.96);
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
}

.profile-delete:hover:not(:disabled) {
  border-color: rgba(248, 113, 113, 0.75);
  background: rgba(153, 27, 27, 0.48);
}

.profile-delete:disabled {
  opacity: 0.62;
  cursor: wait;
}
</style>
