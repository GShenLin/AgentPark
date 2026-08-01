<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { listAgentProfiles, type AgentProfile } from '../../api'
import { agentProfileDescription } from '../../composables/agentProfilePresentation'
import AgentProfileChoiceSummary from './AgentProfileChoiceSummary.vue'

const props = defineProps<{
  nodeTypeId: string
  busy?: boolean
}>()

const emit = defineEmits<{
  load: [profileId: string]
  error: [message: string]
}>()

const rootEl = ref<HTMLElement | null>(null)
const profiles = ref<AgentProfile[]>([])
const loading = ref(false)
const menuOpen = ref(false)
const activeProfile = ref<AgentProfile | null>(null)
const descriptionPopoverStyle = ref<Record<string, string>>({})

const compatibleProfiles = computed(() => {
  const nodeTypeId = String(props.nodeTypeId || '').trim()
  return profiles.value
    .filter((profile) => String(profile.node_type_id || '').trim() === nodeTypeId)
    .sort((left, right) => String(left.name || left.id).localeCompare(String(right.name || right.id)))
})

const disabled = computed(() => props.busy || loading.value || compatibleProfiles.value.length === 0)

async function refreshProfiles() {
  loading.value = true
  try {
    profiles.value = await listAgentProfiles()
  } catch (error) {
    emit('error', error instanceof Error ? error.message : String(error || 'Failed to load Profiles'))
  } finally {
    loading.value = false
  }
}

function closeMenu() {
  menuOpen.value = false
  activeProfile.value = null
}

function toggleMenu() {
  if (disabled.value) return
  menuOpen.value = !menuOpen.value
}

function selectProfile(profileId: string) {
  const safeProfileId = String(profileId || '').trim()
  if (!safeProfileId || props.busy) return
  closeMenu()
  emit('load', safeProfileId)
}

function showDescription(profile: AgentProfile, event: Event) {
  if (!agentProfileDescription(profile)) {
    activeProfile.value = null
    return
  }
  const target = event.currentTarget as HTMLElement | null
  if (!target) return
  const rect = target.getBoundingClientRect()
  const gap = 12
  const viewportPadding = 16
  const width = Math.min(440, window.innerWidth - viewportPadding * 2)
  const roomOnRight = window.innerWidth - rect.right
  const placeOnRight = roomOnRight >= width + gap || rect.left < width + gap
  const left = placeOnRight
    ? Math.min(rect.right + gap, window.innerWidth - width - viewportPadding)
    : Math.max(viewportPadding, rect.left - width - gap)
  const top = Math.max(viewportPadding, Math.min(rect.top, window.innerHeight - 180))
  descriptionPopoverStyle.value = {
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    maxHeight: `calc(100vh - ${top + viewportPadding}px)`,
  }
  activeProfile.value = profile
}

function clearDescription(profileId: string) {
  if (activeProfile.value?.id === profileId) activeProfile.value = null
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
    activeProfile.value = null
    document.removeEventListener('pointerdown', onDocumentPointerDown)
  }
})

onMounted(() => {
  void refreshProfiles()
  window.addEventListener('agent-profiles-changed', refreshProfiles)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  window.removeEventListener('agent-profiles-changed', refreshProfiles)
})
</script>

<template>
  <div ref="rootEl" class="profile-load-control">
    <button
      class="profile-load-trigger"
      type="button"
      :disabled="disabled"
      :aria-expanded="menuOpen"
      :title="compatibleProfiles.length === 0 && !loading ? 'No compatible Profiles' : 'Load Profile into this node'"
      @click="toggleMenu"
    >
      {{ loading ? 'Loading...' : (busy ? 'Loading...' : 'LoadProfile') }}
      <span class="profile-load-caret">v</span>
    </button>

    <div v-if="menuOpen" class="profile-load-menu" @pointerdown.stop>
      <button
        v-for="profile in compatibleProfiles"
        :key="profile.id"
        class="profile-load-option"
        type="button"
        :disabled="busy"
        @mouseenter="showDescription(profile, $event)"
        @mouseleave="clearDescription(profile.id)"
        @focus="showDescription(profile, $event)"
        @blur="clearDescription(profile.id)"
        @click="selectProfile(profile.id)"
      >
        <AgentProfileChoiceSummary :profile="profile" :show-description="false" />
      </button>
    </div>

    <Teleport to="body">
      <aside
        v-if="menuOpen && activeProfile"
        class="profile-description-popover"
        :style="descriptionPopoverStyle"
        role="tooltip"
      >
        <strong>{{ activeProfile.name || activeProfile.id }}</strong>
        <p>{{ agentProfileDescription(activeProfile) }}</p>
      </aside>
    </Teleport>
  </div>
</template>

<style scoped>
.profile-load-control {
  position: relative;
  flex: 0 0 auto;
}

.profile-load-trigger {
  min-height: 28px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--theme-panel-node-side-editor-button-border, rgba(148, 163, 184, 0.22));
  border-radius: 8px;
  background: var(--theme-panel-node-side-editor-button-background, rgba(15, 23, 42, 0.9));
  color: var(--theme-panel-node-side-editor-button-text, #f8fafc);
  padding: 5px 8px;
  font-size: 11px;
  cursor: pointer;
}

.profile-load-trigger:hover:not(:disabled) {
  border-color: var(--accent-blue, #38bdf8);
}

.profile-load-trigger:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.profile-load-caret {
  color: var(--theme-panel-node-side-editor-text-secondary, rgba(148, 163, 184, 0.84));
  font-size: 9px;
}

.profile-load-menu {
  position: absolute;
  z-index: 12;
  top: calc(100% + 6px);
  left: 0;
  width: min(360px, calc(100vw - 32px));
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

.profile-load-option {
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: rgba(226, 232, 240, 0.95);
  padding: 7px 8px;
  text-align: left;
  cursor: pointer;
}

.profile-load-option:hover:not(:disabled) {
  border-color: rgba(56, 189, 248, 0.42);
  background: rgba(14, 116, 144, 0.18);
}

.profile-load-option:focus-visible {
  border-color: rgba(56, 189, 248, 0.72);
  outline: 1px solid rgba(56, 189, 248, 0.72);
}

.profile-description-popover {
  position: fixed;
  z-index: 1000;
  box-sizing: border-box;
  overflow: hidden;
  padding: 16px 18px;
  border: 1px solid rgba(56, 189, 248, 0.52);
  border-radius: 12px;
  background: rgba(2, 6, 23, 0.98);
  color: rgba(241, 245, 249, 0.98);
  box-shadow: 0 20px 54px rgba(0, 0, 0, 0.52);
  pointer-events: none;
}

.profile-description-popover strong {
  display: block;
  margin-bottom: 8px;
  color: rgba(125, 211, 252, 0.98);
  font-size: 13px;
  line-height: 1.4;
}

.profile-description-popover p {
  margin: 0;
  font-size: 18px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

</style>
