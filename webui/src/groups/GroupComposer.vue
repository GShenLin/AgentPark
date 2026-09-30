<script setup lang="ts">
import { computed, ref } from 'vue'
import MessageComposer from '../components/MessageComposer.vue'
import { useMessageAttachments } from '../composables/useMessageAttachments'
import { attachmentResource, type MessageAttachment } from '../composables/messageAttachments'
import { useAudioRecorder } from '../composables/useAudioRecorder'
import { createBrowserUuid } from '../utils/browserId'
import { groupApi, type GroupMember, type GroupMessage } from './groupApi'

const props = withDefaults(defineProps<{ graphId: string; groupId: string; members: GroupMember[]; ready?: boolean }>(), { ready: true })
const emit = defineEmits<{ sent: [] }>()
const text = ref(''), error = ref(''), sending = ref(false)
const files = ref<MessageAttachment[]>([])
const intent = ref<'action' | 'update'>('action')
const recipient = ref('')
const attachments = useMessageAttachments({ text, attachments: files,
  context: () => `${props.graphId}:${props.groupId}`, onError: message => { error.value = message } })
const audio = useAudioRecorder()
let request: GroupMessage | null = null
const validRecipient = computed(() => !recipient.value || props.members.some(member => member.node_id === recipient.value))
const canSend = computed(() => !!(text.value.trim() || files.value.length) && !audio.recording.value
  && (intent.value === 'update' || validRecipient.value))
const sendLabel = computed(() => intent.value === 'update' ? '发布动态' : recipient.value ? `发送给 ${recipient.value}` : '广播给全组')

async function record() {
  error.value = ''
  try {
    if (!audio.recording.value) await audio.start()
    else await attachments.addFiles([await audio.stop()])
  } catch (reason) { error.value = reason instanceof Error ? reason.message : String(reason) }
}

async function send() {
  if (!props.ready || !canSend.value || sending.value || attachments.isUploading.value) return
  const content = { text: text.value.trim(), attachments: files.value.map(file => attachmentResource(file, 'group_composer')),
    intent: intent.value, recipient_id: intent.value === 'action' && recipient.value ? recipient.value : undefined }
  const previousContent = request && { text: request.text, attachments: request.attachments,
    intent: request.intent, recipient_id: request.recipient_id }
  if (!request || JSON.stringify(previousContent) !== JSON.stringify(content)) {
    request = { ...content, request_id: createBrowserUuid() }
  }
  sending.value = true; error.value = ''
  try {
    await groupApi.send(props.graphId, props.groupId, request)
    text.value = ''; files.value = []; request = null
    emit('sent')
  } catch (reason) { error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { sending.value = false }
}
</script>

<template>
  <div class="group-composer">
    <p v-if="error" role="alert">{{ error }}</p>
    <div class="group-routing">
      <label>消息类型<select v-model="intent" :disabled="sending || !ready"><option value="action">请求处理</option><option value="update">共享动态（不唤醒成员）</option></select></label>
      <label v-if="intent === 'action'">接收人<select v-model="recipient" :disabled="sending || !ready"><option value="">全组成员</option><option v-for="member in members" :key="member.node_id" :value="member.node_id">{{ member.node_id }}</option></select></label>
      <span v-else>仅记录到组内动态，不启动 Agent。</span>
    </div>
    <p v-if="intent === 'action' && !validRecipient" role="alert">接收人已离组，请重新选择。</p>
    <MessageComposer v-model:input-text="text" :attachments="files" :can-send="canSend"
      :disabled="sending || !ready" :is-uploading-files="attachments.isUploading.value"
      title="组内消息" :placeholder="intent === 'update' ? '记录进展或补充资料，不需要成员回复…' : '向选定成员发布任务，也可添加或粘贴图片、文件…'"
      :send-label="sending ? '发送中…' : sendLabel"
      :audio-input-enabled="true" :audio-recording="audio.recording.value" :audio-recording-supported="audio.supported.value"
      @toggle-audio-recording="record" @add-files="attachments.addFiles" @drop-input="attachments.drop"
      @paste-input="attachments.paste" @remove-attachment="attachments.remove" @send="send" />
  </div>
</template>

<style scoped>
.group-composer { min-width: 0; max-height: 38dvh; overflow: auto; }
.group-routing { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; margin-bottom: 8px; font-size: 13px; }
.group-routing label { display: flex; align-items: center; gap: 8px; }
.group-routing select { max-width: 230px; padding: 5px 8px; }
.group-routing span { color: var(--text-muted); }
p { color: var(--accent-red); margin: 0 0 8px; overflow-wrap: anywhere; }
</style>
