<script setup lang="ts">
import type { AgentProfile } from '../../api'
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'

defineProps<{
  profile: AgentProfile | null
  dirty: boolean
  loading: boolean
  saving: boolean
  deleting: boolean
}>()

defineEmits<{
  delete: []
  reload: []
  save: []
}>()
</script>

<template>
  <div class="profile-toolbar">
    <div class="profile-heading">
      <strong>{{ profile?.name || 'NodeProfilerEditor' }}</strong>
      <span v-if="profile">{{ profile.id }} · {{ profile.node_type_id }}</span>
      <em v-if="dirty">Unsaved</em>
    </div>
    <div class="profile-actions">
      <DangerButton
        compact
        :disabled="!profile || loading || saving || deleting"
        @click="$emit('delete')"
      >
        {{ deleting ? 'Deleting...' : 'Delete Profile' }}
      </DangerButton>
      <ActionButton compact :disabled="loading || saving || deleting" @click="$emit('reload')">Reload</ActionButton>
      <ActionButton
        variant="primary"
        compact
        :disabled="!dirty || loading || saving || deleting"
        @click="$emit('save')"
      >
        {{ saving ? 'Saving...' : 'Save Profile' }}
      </ActionButton>
    </div>
  </div>
</template>

<style scoped>
.profile-toolbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--theme-panel-settings-panel-editor-border, var(--border-subtle));
  background: var(--theme-panel-settings-panel-editor-toolbar-background, var(--bg-secondary));
}

.profile-heading {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.profile-heading strong,
.profile-heading span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-heading strong {
  color: var(--text-primary);
  font-size: 13px;
}

.profile-heading span {
  color: var(--text-tertiary);
  font: 11px/1.3 'Consolas', 'Menlo', monospace;
}

.profile-heading em {
  flex: 0 0 auto;
  color: #fcd34d;
  font-size: 11px;
  font-style: normal;
}

.profile-actions {
  flex: 0 0 auto;
  display: flex;
  gap: 8px;
}

@media (max-width: 960px) {
  .profile-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .profile-actions {
    flex-wrap: wrap;
  }
}
</style>
