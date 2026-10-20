<script setup lang="ts">
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import FormCheckbox from '../FormCheckbox.vue'
import FormSelect from '../FormSelect.vue'
import NodeAppendFilePickerSheet from './NodeAppendFilePickerSheet.vue'
import { actionLabel } from '../../runtimeEventsConfig'
import { useNodeRuntimeEvents } from './useNodeRuntimeEvents'
import type { NodeCard } from './context'

const CONTEXT_ROLE_LABELS: Record<string, string> = {
  developer: 'Developer',
  system: 'System',
  user: 'User',
  assistant: 'Assistant',
}

const props = defineProps<{ node: Pick<NodeCard, 'id'>; graphId: string }>()
const emit = defineEmits<{ error: [message: string] }>()
const {
  loading, applying, status, eventNodes, eventOptions, actionOptions, contextRoleOptions,
  profileOptions, selectingFile, appendFilePickerOpen, appendFilePickerDraft,
  appendFilePickerSelected, appendFilePickerFiles, appendFilePickerLoading,
  targetOptions, appendFilePaths, appendFileLabel, availableEventsFor, refreshEvents,
  addEventNode, updateEvent, addHandler, updateHandler, updateAction, chooseAppendFile,
  closeAppendFilePicker, confirmAppendFile, addProfile, updateProfile, deleteProfile,
  deleteHandler, deleteEventNode
} = useNodeRuntimeEvents(props, message => emit('error', message))
</script>

<template>
  <section class="runtime-events-section">
    <div class="section-head">
      <div>
        <div class="section-title">事件处理</div>
        <div class="section-subtitle">为节点配置触发事件及对应的处理方式</div>
      </div>
      <div class="section-actions">
        <ActionButton compact :disabled="loading || applying" @click="refreshEvents">{{ loading ? '加载中...' : '刷新' }}</ActionButton>
        <ActionButton variant="primary" icon compact :disabled="loading || applying" title="添加事件" aria-label="添加事件" @click="addEventNode">+</ActionButton>
      </div>
    </div>

    <div v-if="status" class="event-status">{{ status }}</div>
    <div v-if="loading" class="empty-hint">正在加载事件配置...</div>
    <div v-else-if="eventNodes.length" class="event-node-list">
      <div v-for="(eventNode, eventIndex) in eventNodes" :key="eventNode.event" class="event-node">
        <div class="event-column">
          <span v-if="!eventOptions.includes(eventNode.event)" class="existing-value">{{ eventNode.event }}</span>
          <FormSelect v-else :model-value="eventNode.event" compact :disabled="applying" aria-label="事件" @change="updateEvent(eventIndex, $event)">
            <option v-for="event in availableEventsFor(eventIndex)" :key="event" :value="event">{{ event }}</option>
          </FormSelect>
          <DangerButton icon :disabled="applying" aria-label="删除事件" title="删除事件" @click="deleteEventNode(eventIndex)">×</DangerButton>
        </div>

        <div class="handler-column">
          <div class="handler-head">
            <span>处理方式</span>
            <ActionButton variant="primary" icon compact :disabled="applying" title="添加处理方式" aria-label="添加处理方式" @click="addHandler(eventIndex)">+</ActionButton>
          </div>
          <div v-if="eventNode.handlers.length" class="handler-list">
            <div v-for="(handler, handlerIndex) in eventNode.handlers" :key="handlerIndex" class="handler-row">
              <span v-if="!actionOptions.includes(handler.action)" class="existing-value">{{ actionLabel(handler.action) }}</span>
              <FormSelect v-else :model-value="handler.action" compact :disabled="applying" aria-label="处理方式" @change="updateAction(eventIndex, handlerIndex, $event)">
                <option v-for="action in actionOptions" :key="action" :value="action">{{ actionLabel(action) }}</option>
              </FormSelect>
              <div v-if="handler.action === 'node.dispatch'" class="profile-list">
                <div v-for="(selectedProfileId, profileIndex) in handler.params?.profile_ids || []" :key="`${selectedProfileId}/${profileIndex}`" class="profile-row">
                  <FormSelect :model-value="selectedProfileId" compact :disabled="applying" aria-label="处理 Agent" @change="updateProfile(eventIndex, handlerIndex, profileIndex, $event)">
                    <option v-for="profileId in profileOptions" :key="profileId" :value="profileId" :disabled="profileId !== selectedProfileId && (handler.params?.profile_ids || []).includes(profileId)">{{ profileId }}</option>
                  </FormSelect>
                  <DangerButton icon :disabled="applying" aria-label="删除 Agent Profile" title="删除 Agent Profile" @click="deleteProfile(eventIndex, handlerIndex, profileIndex)">×</DangerButton>
                </div>
                <ActionButton compact :disabled="applying" @click="addProfile(eventIndex, handlerIndex)">+ Agent Profile</ActionButton>
              </div>
              <div v-else-if="handler.action === 'context.append_file'" class="append-file-field">
                <ActionButton
                  class="append-file-btn"
                  compact
                  :disabled="applying || selectingFile === `${eventIndex}/${handlerIndex}`"
                  :title="appendFilePaths(handler.params?.paths).join('\n') || '选择一个或多个上下文文件'"
                  @click="chooseAppendFile(eventIndex, handlerIndex)"
                >{{ selectingFile === `${eventIndex}/${handlerIndex}` ? '选择中...' : appendFileLabel(handler.params?.paths) }}</ActionButton>
                <FormSelect
                  :model-value="String(handler.params?.role || 'developer')"
                  compact
                  :disabled="applying"
                  aria-label="上下文角色"
                  @change="updateHandler(eventIndex, handlerIndex, { params: { ...(handler.params || {}), role: $event } })"
                >
                  <option v-for="role in contextRoleOptions" :key="role" :value="role">{{ CONTEXT_ROLE_LABELS[role] || role }}</option>
                </FormSelect>
              </div>
              <FormSelect v-else :model-value="handler.target" compact :disabled="applying" aria-label="处理目标" @change="updateHandler(eventIndex, handlerIndex, { target: $event })">
                <option v-for="target in targetOptions(handler.action)" :key="target" :value="target">{{ target }}</option>
              </FormSelect>
              <label
                class="handler-enabled"
                :class="{ disabled: handler.action === 'context.append_file' && !appendFilePaths(handler.params?.paths).length }"
                :title="handler.action === 'context.append_file' && !appendFilePaths(handler.params?.paths).length ? '请先选择上下文文件' : '控制该处理方式是否执行'"
              >
                <FormCheckbox
                  :model-value="handler.enabled !== false"
                  :disabled="applying || (handler.action === 'context.append_file' && !appendFilePaths(handler.params?.paths).length)"
                  :aria-label="`${actionLabel(handler.action)} 是否启用`"
                  @update:model-value="updateHandler(eventIndex, handlerIndex, { enabled: $event })"
                />
                <span>启用</span>
              </label>
              <DangerButton icon :disabled="applying" aria-label="删除处理方式" title="删除处理方式" @click="deleteHandler(eventIndex, handlerIndex)">×</DangerButton>
            </div>
          </div>
          <div v-else class="empty-handler">暂无处理方式，点击右上角 + 添加。</div>
        </div>
      </div>
    </div>
    <div v-else class="empty-state">
      <span>当前节点没有事件配置。</span>
      <ActionButton variant="primary" compact :disabled="applying" @click="addEventNode">+ 添加事件</ActionButton>
    </div>

    <NodeAppendFilePickerSheet
      v-if="appendFilePickerOpen"
      v-model:custom-path="appendFilePickerDraft"
      v-model:selected-paths="appendFilePickerSelected"
      :files="appendFilePickerFiles"
      :loading="appendFilePickerLoading"
      :saving="applying"
      @close="closeAppendFilePicker"
      @confirm="confirmAppendFile"
    />
  </section>
</template>

<style scoped>
.runtime-events-section {
  container: runtime-events / inline-size;
  --event-border: var(--theme-panel-node-side-editor-input-border, #dce4ef);
  --event-text: var(--theme-panel-node-side-editor-input-text, #20314a);
  --event-muted: var(--theme-panel-node-side-editor-text-secondary, #687b94);
  --form-control-border: var(--event-border);
  --form-control-background: var(--theme-panel-node-side-editor-input-background, #fff);
  --form-control-text: var(--event-text);
  --form-control-focus: var(--theme-panel-node-side-editor-input-focus-border, #4269c7);
  color: var(--event-text);
  display: flex; flex-direction: column; gap: 10px; flex: 0 0 auto; border-top: 1px solid var(--event-border); padding-top: 12px; }
.section-head, .section-actions, .handler-head, .event-column { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.section-title { font-size: 13px; font-weight: 700; color: var(--event-text); }
.section-subtitle, .empty-hint, .empty-handler { margin-top: 2px; color: var(--event-muted); font-size: 11px; }
.event-node-list, .handler-list { display: flex; flex-direction: column; gap: 8px; }
.event-node { display: grid; grid-template-columns: minmax(130px, 0.7fr) minmax(0, 2fr); gap: 10px; border: 1px solid var(--event-border); border-radius: 8px; padding: 8px; }
.event-column { align-items: flex-start; }
.event-column .form-select { flex: 1; }
.handler-column { min-width: 0; border-left: 1px solid var(--event-border); padding-left: 10px; }
.handler-head { margin-bottom: 8px; color: var(--event-muted); font-size: 11px; }
.handler-row { display: grid; grid-template-columns: minmax(118px, 0.9fr) minmax(132px, 1.1fr) auto auto; gap: 8px; align-items: center; }
.existing-value { overflow-wrap: anywhere; font-size: 12px; }
.profile-list, .profile-row { display: flex; gap: 6px; align-items: center; }
.profile-list { flex-direction: column; align-items: stretch; }
.profile-row .form-select { flex: 1; }
.append-file-field { display: grid; grid-template-columns: minmax(0, 1fr) minmax(105px, 0.45fr); gap: 6px; }
.append-file-btn { min-width: 0; overflow: hidden; text-align: left; text-overflow: ellipsis; }
.handler-enabled { display: inline-flex; align-items: center; gap: 5px; color: var(--event-text); cursor: pointer; font-size: 11px; white-space: nowrap; }
.handler-enabled.disabled { cursor: default; opacity: 0.55; }
.empty-handler { border: 1px dashed var(--event-border); border-radius: 7px; padding: 9px; }
.empty-state { display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px dashed var(--event-border); border-radius: 8px; color: var(--event-muted); font-size: 12px; padding: 10px; }
.event-status { border: 1px solid rgba(45, 212, 191, 0.24); border-radius: 8px; background: rgba(15, 118, 110, 0.14); color: var(--event-text); font-size: 12px; padding: 8px 10px; }
@container runtime-events (max-width: 620px) {
  .event-node, .handler-row { grid-template-columns: 1fr; }
  .handler-column { border-left: 0; border-top: 1px solid var(--event-border); padding: 10px 0 0; }
}
</style>
