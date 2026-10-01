<script setup lang="ts">
import { inject, ref } from 'vue'
import { settingsNavigationKey } from './settingsNavigation'
defineProps<{ title: string; expanded?: boolean }>()
const compact = inject(settingsNavigationKey, null)?.compact ?? ref(false)
</script>

<template>
  <details class="settings-field-group" :open="!compact || expanded">
    <summary>{{ title }}</summary>
    <div class="settings-field-group-body"><slot /></div>
  </details>
</template>

<style scoped>
.settings-field-group { flex: 0 0 auto; min-width: 0; border: 1px solid var(--border-subtle); border-radius: 10px; }
summary { padding: 12px; cursor: pointer; font-size: 14px; font-weight: 600; color: var(--text-primary); min-height: 44px; box-sizing: border-box; }
.settings-field-group-body { padding: 0 12px 14px; }
</style>
