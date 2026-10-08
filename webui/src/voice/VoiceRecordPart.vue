<script setup lang="ts">
import { ref } from 'vue'
import { voiceDuration, type VoiceRecord } from './voiceRecord'

defineProps<{ record: VoiceRecord }>()
const expanded = ref(false)
</script>

<template>
  <details class="voice-record" @toggle="expanded = ($event.target as HTMLDetailsElement).open">
    <summary>
      <strong>语音记录</strong>
      <span>{{ voiceDuration(record.duration_ms) }} · {{ record.lines.length }} 条对话</span>
      <span>{{ record.status === 'error' ? '通话中断' : '通话结束' }}</span>
    </summary>
    <div v-if="expanded" class="voice-record-content">
      <p class="voice-record-time">{{ record.started_at }} — {{ record.ended_at }}</p>
      <p v-if="!record.lines.length">本次通话没有收到文字转写。</p>
      <ol v-else>
        <li v-for="(line, index) in record.lines" :key="index" :class="`voice-line-${line.role}`">
          <div class="voice-line-head">
            <strong>{{ line.role === 'user' ? '输入语音' : '节点' }}</strong>
            <span>{{ voiceDuration(line.offset_ms) }}</span>
            <span v-if="line.incomplete">未完成</span>
          </div>
          <p>{{ line.text }}</p>
        </li>
      </ol>
    </div>
  </details>
</template>

<style scoped>
.voice-record { color: var(--text-primary); border: 1px solid var(--border-medium); border-radius: 8px; min-width: 0; }
summary { cursor: pointer; padding: 12px; line-height: 1.7; overflow-wrap: anywhere; }
summary span { margin-left: 10px; color: var(--text-secondary); font-size: 12px; }
.voice-record-content { padding: 0 12px 12px; }
.voice-record-time, .voice-line-head span { color: var(--text-secondary); font-size: 12px; }
ol { list-style: none; padding: 0; margin: 0; display: grid; gap: 12px; }
li { padding: 10px; border-radius: 6px; background: var(--bg-secondary); }
.voice-line-head { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
p { margin: 6px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; }
</style>
