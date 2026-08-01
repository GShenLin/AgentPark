<script setup lang="ts">
import type { AgentProfile } from '../api'
import AgentProfileChoiceSummary from '../components/agent-board/AgentProfileChoiceSummary.vue'
import DialogCloseButton from '../components/DialogCloseButton.vue'

defineProps<{
  open: boolean
  profiles: AgentProfile[]
}>()

const emit = defineEmits<{
  close: []
  select: [profile: AgentProfile]
}>()
</script>

<template>
  <div v-if="open" class="profile-picker-backdrop" @click.self="emit('close')">
    <section class="profile-picker-sheet" role="dialog" aria-modal="true" aria-label="加载节点预设">
      <header class="profile-picker-head">
        <div>
          <div class="profile-picker-title">LoadProfile</div>
          <div class="profile-picker-subtitle">选择 Profile 后更新当前节点配置与事件，节点名称保持不变</div>
        </div>
        <DialogCloseButton aria-label="关闭预设选择" @click="emit('close')" />
      </header>

      <div class="profile-picker-body">
        <div v-if="profiles.length === 0" class="profile-picker-empty">还没有可用的 Profile。</div>
        <button
          v-for="profile in profiles"
          :key="profile.id"
          class="profile-picker-option"
          type="button"
          @click="emit('select', profile)"
        >
          <AgentProfileChoiceSummary :profile="profile" />
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.profile-picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 70;
  display: flex;
  align-items: flex-end;
  background: var(--ui-dialog-backdrop);
}

.profile-picker-sheet {
  width: 100%;
  max-height: min(72vh, 620px);
  display: flex;
  flex-direction: column;
  border: 1px solid var(--ui-dialog-border);
  border-width: 1px 0 0;
  border-radius: var(--ui-dialog-radius) var(--ui-dialog-radius) 0 0;
  background: var(--ui-dialog-background);
  color: var(--ui-dialog-text);
  box-shadow: var(--ui-dialog-shadow);
}

.profile-picker-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px;
  border-bottom: 1px solid var(--ui-dialog-divider);
}

.profile-picker-title {
  color: rgba(248, 250, 252, 0.98);
  font-size: 16px;
  font-weight: 750;
}

.profile-picker-subtitle {
  margin-top: 3px;
  color: rgba(148, 163, 184, 0.9);
  font-size: 12px;
}

.profile-picker-body {
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px calc(18px + env(safe-area-inset-bottom));
}

.profile-picker-option {
  width: 100%;
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.72);
  color: rgba(226, 232, 240, 0.96);
  text-align: left;
}

.profile-picker-option:active {
  border-color: rgba(56, 189, 248, 0.72);
  background: rgba(14, 116, 144, 0.24);
}

.profile-picker-empty {
  padding: 22px 12px;
  color: rgba(148, 163, 184, 0.9);
  font-size: 13px;
  text-align: center;
}
</style>
