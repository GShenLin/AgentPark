<script setup lang="ts">
import type { AgentProfile } from '../api'

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
        <button class="profile-picker-close" type="button" aria-label="关闭预设选择" @click="emit('close')">x</button>
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
          <span class="profile-picker-name">{{ profile.name || profile.id }}</span>
          <span class="profile-picker-id">{{ profile.id }}</span>
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
  background: rgba(2, 6, 23, 0.76);
}

.profile-picker-sheet {
  width: 100%;
  max-height: min(72vh, 620px);
  display: flex;
  flex-direction: column;
  border-top: 1px solid rgba(56, 189, 248, 0.3);
  background: #08111f;
  box-shadow: 0 -18px 44px rgba(2, 6, 23, 0.5);
}

.profile-picker-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
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

.profile-picker-close {
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  padding: 0;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.78);
  color: rgba(226, 232, 240, 0.94);
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
  min-height: 52px;
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

.profile-picker-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 650;
}

.profile-picker-id {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  color: rgba(148, 163, 184, 0.88);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-picker-empty {
  padding: 22px 12px;
  color: rgba(148, 163, 184, 0.9);
  font-size: 13px;
  text-align: center;
}
</style>
