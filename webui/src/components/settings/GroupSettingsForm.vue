<script setup lang="ts">
import { computed } from 'vue'
import ActionButton from '../ActionButton.vue'
import FormCheckbox from '../FormCheckbox.vue'

const props = defineProps<{
  data: Record<string, unknown>; defaults: Record<string, unknown>; disabled?: boolean
}>()
const emit = defineEmits<{ 'update:data': [value: Record<string, unknown>] }>()
const toolFields = [
  ['group_board', '读取任务看板'], ['group_board_detail', '读取看板详情'],
  ['group_events', '读取组内动态'], ['group_send_message', '向成员交接工作'],
  ['group_post_update', '记录进展'], ['group_broadcast_message', '广播行动请求'],
  ['group_create_task', '创建任务'], ['group_update_task', '更新与完成任务'],
] as const
const mainFields = [
  ['context_prompt', '成员协作提示词', '每次 Agent 执行时注入，指导任务分工、依赖处理、交接和结束本轮工作。'],
  ['notification_prompt', '通知处理提示词', '节点收到 Group 通知时使用，指导如何处理任务和消息、如何回复。'],
] as const
const policy = computed(() => props.data.task_notifications as { assignment: boolean; dependency_ready: boolean })
const tools = computed(() => props.data.tool_prompts as Record<string, string>)
const valid = computed(() => mainFields.every(([key]) => typeof props.data[key] === 'string')
  && policy.value != null && typeof policy.value.assignment === 'boolean' && typeof policy.value.dependency_ready === 'boolean'
  && tools.value != null && toolFields.every(([key]) => typeof tools.value[key] === 'string'))
function setValue(key: string, value: unknown) { emit('update:data', { ...props.data, [key]: value }) }
function setTool(key: string, value: string) { setValue('tool_prompts', { ...tools.value, [key]: value }) }
function resetTool(key: string) { setTool(key, (props.defaults.tool_prompts as Record<string, string>)[key]!) }
</script>

<template>
  <section v-if="valid" class="group-settings-form" aria-label="Group 设置">
    <header>
      <div><h2>Group</h2><p>管理所有 Group 的任务通知与协作提示词。所有类型的节点均可加入 Group。</p></div>
      <ActionButton compact :disabled="disabled" @click="emit('update:data', { ...defaults })">全部恢复默认</ActionButton>
    </header>
    <p class="scope-note">保存后，新任务变化和下一次执行使用新设置；已排队通知和正在进行的工作继续处理。协作工具由支持它们的节点使用。</p>

    <section class="policy-section" aria-labelledby="group-notification-heading">
      <h3 id="group-notification-heading">任务推进</h3>
      <label class="policy-row">
        <FormCheckbox :model-value="policy.assignment" :disabled="disabled"
          @update:model-value="setValue('task_notifications', { ...policy, assignment: $event })" />
        <span>分配或修改任务后通知负责人<small>任务已就绪时，自动将新的工作要求加入负责节点的执行队列。</small></span>
      </label>
      <label class="policy-row">
        <FormCheckbox :model-value="policy.dependency_ready" :disabled="disabled"
          @update:model-value="setValue('task_notifications', { ...policy, dependency_ready: $event })" />
        <span>前置任务完成后通知后续负责人<small>所有前置任务完成后，自动推进已分配的后续任务。</small></span>
      </label>
      <p>关闭自动通知后，任务仍保留在看板中，可以通过组内消息要求成员执行。消息投递不受这些开关影响。</p>
    </section>

    <details v-for="[key, title, help] in mainFields" :key="key">
      <summary>{{ title }}</summary>
      <div class="prompt-body">
        <p>{{ help }}</p>
        <textarea :value="data[key] as string" :aria-label="title" :disabled="disabled" rows="12" maxlength="32000"
          @input="setValue(key, ($event.target as HTMLTextAreaElement).value)" />
        <ActionButton compact :disabled="disabled" @click="setValue(key, defaults[key])">恢复此项默认</ActionButton>
      </div>
    </details>

    <details>
      <summary>协作工具提示词 · {{ toolFields.length }} 项</summary>
      <div class="prompt-body">
        <p>调整模型使用协作工具时看到的说明。提示词可以留空；工具参数、权限与任务依赖校验仍由系统执行。</p>
        <details v-for="[key, title] in toolFields" :key="key">
          <summary>{{ title }}</summary>
          <div class="prompt-body">
            <textarea :value="tools[key]" :aria-label="title" :disabled="disabled" rows="6" maxlength="32000"
              @input="setTool(key, ($event.target as HTMLTextAreaElement).value)" />
            <ActionButton compact :disabled="disabled" @click="resetTool(key)">恢复此项默认</ActionButton>
          </div>
        </details>
      </div>
    </details>
    <p>恢复默认会先更新当前草稿，点击页面顶部的保存后生效。</p>
  </section>
  <p v-else role="alert">当前 JSON 草稿的 Group 字段不完整或类型不正确。请在 JSON 模式修正并保存，或重新加载设置。</p>
</template>

<style scoped>
.group-settings-form { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 14px; padding: 20px 24px; }
header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
h2, h3 { margin: 0 0 8px; color: var(--text-primary); }
h2 { font-size: 18px; } h3 { font-size: 14px; }
p, small { color: var(--text-secondary); line-height: 1.6; font-size: 12px; }
p { margin: 0; } small { display: block; margin-top: 4px; }
.scope-note { padding: 12px; background: var(--bg-secondary); border-radius: 8px; }
.policy-section, details { flex-shrink: 0; border: 1px solid var(--border-subtle); border-radius: 10px; }
.policy-section { padding: 16px; }
.policy-row { display: flex; align-items: flex-start; gap: 10px; margin: 14px 0; font-size: 13px; color: var(--text-primary); }
.policy-row input { margin-top: 3px; }
summary { padding: 14px; cursor: pointer; font-size: 14px; font-weight: 600; color: var(--text-primary); }
.prompt-body { display: flex; flex-direction: column; align-items: stretch; gap: 12px; padding: 0 14px 14px; }
.prompt-body > button { align-self: flex-end; }
textarea { box-sizing: border-box; width: 100%; resize: vertical; min-height: 120px; padding: 12px; border: 1px solid var(--border-subtle); border-radius: 8px; background: var(--bg-primary); color: var(--text-primary); font: inherit; font-size: 13px; line-height: 1.65; }
textarea:focus-visible { outline: 2px solid var(--text-accent); outline-offset: 2px; }
@media (max-width: 600px) { header { flex-direction: column; } .group-settings-form { padding: 16px 12px; } }
</style>
