<script setup lang="ts">
import { ref } from 'vue'
import ToolStatsSettingsPanel from './ToolStatsSettingsPanel.vue'
import TurnAuditPanel from './TurnAuditPanel.vue'

const activeView = ref<'audit' | 'stats'>('audit')
</script>

<template>
  <div class="static-settings">
    <div class="static-settings-tabs" role="tablist" aria-label="Static views">
      <button
        type="button"
        role="tab"
        :aria-selected="activeView === 'audit'"
        :class="{ active: activeView === 'audit' }"
        @click="activeView = 'audit'"
      >
        Full Chain Audit
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="activeView === 'stats'"
        :class="{ active: activeView === 'stats' }"
        @click="activeView = 'stats'"
      >
        Tool Statistics
      </button>
    </div>
    <TurnAuditPanel v-if="activeView === 'audit'" />
    <ToolStatsSettingsPanel v-else />
  </div>
</template>

<style scoped>
.static-settings {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.static-settings-tabs {
  flex: 0 0 auto;
  display: flex;
  gap: 6px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
}

.static-settings-tabs button {
  min-height: 32px;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 0 12px;
  color: var(--text-tertiary);
  background: transparent;
}

.static-settings-tabs button.active {
  border-color: rgba(59, 130, 246, 0.32);
  color: var(--text-primary);
  background: var(--accent-blue-soft);
}
</style>
