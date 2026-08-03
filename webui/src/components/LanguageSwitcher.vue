<script setup lang="ts">
import { useI18n } from '../i18n'

withDefaults(defineProps<{
  compact?: boolean
}>(), {
  compact: false,
})

const { currentLocale, nextLocale, cycleLocale, t } = useI18n()
</script>

<template>
  <button
    class="language-switcher"
    :class="{ compact }"
    type="button"
    :aria-label="t('language.next', { language: nextLocale.label })"
    :title="t('language.current', { language: currentLocale.label })"
    @click="cycleLocale"
  >
    <span class="language-icon" aria-hidden="true">文</span>
    <span>{{ nextLocale.shortLabel }}</span>
  </button>
</template>

<style scoped>
.language-switcher {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid var(--theme-panel-topbar-button-border, transparent);
  border-radius: var(--ui-control-radius, 6px);
  background: var(--theme-panel-topbar-button-background, transparent);
  color: var(--theme-panel-topbar-button-text, var(--text-secondary));
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease, border-color 0.15s ease;
}

.language-switcher:hover {
  border-color: var(--theme-panel-topbar-button-hover-border, transparent);
  background: var(--theme-panel-topbar-button-hover-background, var(--bg-hover));
  color: var(--theme-panel-topbar-button-hover-text, var(--text-primary));
}

.language-switcher:focus-visible {
  outline: 2px solid var(--theme-panel-topbar-button-active-text, var(--accent-blue));
  outline-offset: 2px;
}

.language-switcher.compact {
  min-height: 30px;
  padding: 0 8px;
}

.language-icon {
  font-size: 13px;
  font-weight: 700;
}
</style>
