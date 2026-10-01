<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SettingsSectionInfo } from '../../settingsApi'
import { t } from '../../i18n'
import { SECTION_MESSAGE_KEYS } from './settingsSections'
import FormTextInput from '../FormTextInput.vue'

const props = defineProps<{ sections: SettingsSectionInfo[]; active: string; disabled: boolean }>()
defineEmits<{ select: [id: string] }>()
const query = ref('')
const definitions = [
  { key: 'models', ids: ['model-provider', 'node-profiler-editor', 'defaults', 'companion'] },
  { key: 'capabilities', ids: ['harness', 'skills', 'knowledge'] },
  { key: 'connections', ids: ['authorization', 'gateway', 'peer-network', 'node-sync'] },
  { key: 'diagnostics', ids: ['provider-test', 'pressure', 'tool-stats', 'events'] },
  { key: 'system', ids: ['theme', 'exit'] },
]
const label = (section: SettingsSectionInfo) => SECTION_MESSAGE_KEYS[section.id]
  ? t(SECTION_MESSAGE_KEYS[section.id]!) : section.label
const groups = computed(() => {
  const known = new Set(definitions.flatMap(group => group.ids))
  return [...definitions, { key: 'other', ids: props.sections.filter(section => !known.has(section.id)).map(section => section.id) }]
    .map(group => ({
      ...group,
      sections: group.ids.flatMap(id => props.sections.filter(section => section.id === id))
        .filter(section => `${label(section)} ${section.id}`.toLowerCase().includes(query.value.trim().toLowerCase())),
    })).filter(group => group.sections.length)
})
</script>

<template>
  <nav class="settings-catalog" :aria-label="t('settings.sectionsAria')">
    <FormTextInput v-model="query" type="search" :placeholder="t('settings.searchSections')" :aria-label="t('settings.searchSections')" />
    <section v-for="group in groups" :key="group.key" class="catalog-group">
      <h2>{{ t(`settings.group.${group.key}`) }}</h2>
      <button v-for="section in group.sections" :key="section.id" type="button" :disabled="disabled"
        :class="{ active: active === section.id }" @click="$emit('select', section.id)">
        <span>{{ label(section) }}</span><span aria-hidden="true">›</span>
      </button>
    </section>
    <p v-if="!groups.length" role="status">{{ t('settings.noMatchingSections') }}</p>
  </nav>
</template>

<style scoped>
.settings-catalog { flex: 1; min-height: 0; overflow: auto; padding: 16px 12px max(20px, env(safe-area-inset-bottom)); background: var(--bg-primary); }
.catalog-group { margin-top: 22px; }
.catalog-group h2 { margin: 0 4px 8px; font-size: 13px; color: var(--text-secondary); }
.catalog-group button { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; min-height: 50px; padding: 12px 14px; border: 1px solid var(--border-subtle); background: var(--bg-secondary); color: var(--text-primary); text-align: left; font: inherit; }
.catalog-group button + button { border-top: 0; }
.catalog-group button:first-of-type { border-radius: 10px 10px 0 0; }
.catalog-group button:last-of-type { border-radius: 0 0 10px 10px; }
.catalog-group button:only-of-type { border-radius: 10px; }
.catalog-group button.active { color: var(--text-accent); }
.catalog-group button:disabled { opacity: .5; }
</style>
