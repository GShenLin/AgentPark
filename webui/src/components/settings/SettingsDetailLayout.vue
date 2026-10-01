<script setup lang="ts">
import ActionButton from '../ActionButton.vue'
import { t } from '../../i18n'

defineProps<{ detailOpen: boolean }>()
defineEmits<{ back: [] }>()
</script>

<template>
  <div class="settings-detail-layout settings-split" :class="{ 'is-detail-open': detailOpen }">
    <slot name="list" />
    <div class="settings-detail-pane">
      <div class="settings-detail-back">
        <ActionButton @click="$emit('back')">‹ {{ t('settings.backToList') }}</ActionButton>
      </div>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.settings-detail-pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; }
.settings-detail-pane > :deep(.settings-split__detail) { flex: 1; }
.settings-detail-back { display: none; }
@media (max-width: 960px) {
  .settings-detail-layout { display: flex; flex-direction: column; gap: 0; }
  .settings-detail-pane { display: none; flex: 1; }
  .is-detail-open > :deep(.settings-split__side) { display: none; }
  .is-detail-open > .settings-detail-pane { display: flex; }
  .settings-detail-back { display: flex; flex: 0 0 auto; padding: 8px 12px; border-bottom: 1px solid var(--border-subtle); }
  .settings-detail-layout > :deep(.settings-split__side) { flex: 1; padding: 12px; border: 0; }
  .settings-detail-pane > :deep(.settings-split__detail) { padding: 12px; }
}
</style>
