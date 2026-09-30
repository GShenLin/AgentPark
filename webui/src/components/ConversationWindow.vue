<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { DEFAULT_AGENT_PANEL_SETTINGS } from '../agentPanelSettings'
import { useDialogLifecycle } from '../composables/useDialogLifecycle'
import { conversationWindowSettings } from './conversationWindowSettings'
import { cloudBoardSession } from '../portal/boardSession'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{ floating?: boolean; label: string }>(), { floating: true })
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
const settings = inject(conversationWindowSettings, ref(DEFAULT_AGENT_PANEL_SETTINGS))
const session = inject(cloudBoardSession, null)
const suspended = computed(() => !!session && session.phase.value !== 'ready')
const dimensions = computed(() => props.floating ? {
  '--conversation-width': `${settings.value.width}px`, '--conversation-height': `${settings.value.height}px`,
} : {})
useDialogLifecycle(panel, computed(() => props.floating), () => emit('close'))
</script>

<template>
  <Teleport to="#app" :disabled="!floating">
    <div v-if="floating" class="conversation-backdrop" :inert="suspended" @click.self="emit('close')" />
    <aside ref="panel" v-bind="$attrs" class="conversation-window" :class="{ 'is-floating': floating, 'is-docked': !floating, 'chat-appearance': floating }"
      :style="dimensions" :role="floating ? 'dialog' : undefined" :aria-modal="floating ? 'true' : undefined"
      :aria-label="floating ? label : undefined" :tabindex="floating ? -1 : undefined" :inert="suspended">
      <slot />
    </aside>
  </Teleport>
</template>

<style scoped>
.conversation-backdrop { position: fixed; inset: 0; z-index: 500; background: var(--ui-dialog-backdrop, #0005); }
.conversation-window {
  display: flex; flex-direction: column; min-height: 0; overflow: hidden; box-sizing: border-box;
}
/* Teleport does not forward a parent's scope ID to this aside. Own the
   docked height boundary here so descendants can form real scroll containers. */
.conversation-window.is-docked {
  position: absolute; top: 0; right: 0; bottom: 0; width: 560px; z-index: 110;
  background-color: var(--theme-panel-memory-panel-background-color, var(--bg-primary));
  background-image: var(--theme-panel-memory-panel-background-image, none);
  background-size: var(--theme-panel-memory-panel-background-size, cover);
  background-position: var(--theme-panel-memory-panel-background-position, center);
  background-repeat: var(--theme-panel-memory-panel-background-repeat, no-repeat);
  background-blend-mode: var(--theme-panel-memory-panel-background-blend-mode, normal);
}
.conversation-window.is-docked.collapsed { align-items: center; justify-content: center; }
.conversation-window.is-floating {
  position: fixed; inset: auto auto 32px 50%; transform: translateX(-50%); z-index: 510;
  width: min(var(--conversation-width), calc(100vw - 80px)); height: min(var(--conversation-height), calc(100dvh - 80px));
  border: 1px solid var(--ui-dialog-border); border-radius: 20px; background: var(--theme-panel-memory-panel-background-color, var(--bg-primary));
  color: var(--theme-panel-memory-panel-text-primary, var(--text-primary)); box-shadow: var(--ui-dialog-shadow); outline: none;
}
@media (max-width: 720px) {
  .conversation-window.is-floating { inset: 0; transform: none; width: 100%; height: 100dvh; border-radius: 0; }
}
</style>
