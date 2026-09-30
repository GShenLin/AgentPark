<script setup lang="ts">
import DialogCloseButton from './DialogCloseButton.vue'
import { t } from '../i18n'
withDefaults(defineProps<{ title: string; subtitle?: string | null; closable?: boolean; closeLabel?: string }>(), { closable: true })
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <header class="panel-head">
    <div class="panel-left"><div class="panel-title">{{ title }}</div><div v-if="subtitle" class="panel-meta" :title="subtitle">{{ subtitle }}</div></div>
    <div class="conversation-header-actions"><slot /></div>
    <DialogCloseButton v-if="closable" :aria-label="closeLabel || t('common.close')" @click="emit('close')" />
  </header>
</template>

<style scoped>
.panel-head { flex-shrink: 0; display: flex; align-items: center; gap: 10px; padding: 14px 20px; border-bottom: 1px solid var(--theme-panel-memory-panel-header-border, var(--border-light)); background: var(--theme-panel-memory-panel-header-background, var(--bg-primary)); }
.panel-left { min-width: 0; margin-right: auto; display: flex; flex-direction: column; gap: 3px; }
.panel-title { font-size: var(--theme-panel-memory-panel-font-title, 15px); font-weight: 600; overflow-wrap: anywhere; }
.panel-meta { max-width: 360px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-size: 11px; color: var(--theme-panel-memory-panel-text-muted, var(--text-secondary)); }
.conversation-header-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 10px; min-width: 0; }
.conversation-header-actions:empty { display: none; }
@media (max-width: 720px) { .panel-head { padding: 14px; } }
</style>
