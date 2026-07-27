<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  busy?: boolean
  error?: string
}>()

const emit = defineEmits<{
  submit: [username: string]
}>()

const username = ref('')

function submit() {
  const value = username.value.trim()
  if (!value || props.busy) return
  emit('submit', value)
}
</script>

<template>
  <div class="access-overlay">
    <form class="access-dialog" @submit.prevent="submit">
      <h1>登记访问用户</h1>
      <p>这是你第一次从当前设备访问 AgentPark，请填写用户名。填写后会自动记录当前访问 IP。</p>
      <label>
        <span>用户名</span>
        <input v-model="username" maxlength="80" autocomplete="name" autofocus>
      </label>
      <div v-if="error" class="access-error">{{ error }}</div>
      <button type="submit" :disabled="busy || !username.trim()">
        {{ busy ? '登记中…' : '进入 AgentPark' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.access-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: grid;
  place-items: center;
  padding: 24px;
  background: #08111f;
}
.access-dialog {
  width: min(440px, 100%);
  display: grid;
  gap: 18px;
  padding: 28px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 14px;
  background: #111c2e;
  color: #e5edf8;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.38);
}
h1, p { margin: 0; }
p { color: #aebbd0; line-height: 1.55; }
label { display: grid; gap: 8px; }
input {
  min-height: 42px;
  padding: 0 12px;
  border: 1px solid #34445f;
  border-radius: 8px;
  background: #0b1525;
  color: inherit;
}
button {
  min-height: 42px;
  border: 0;
  border-radius: 8px;
  background: #2563eb;
  color: white;
  cursor: pointer;
}
button:disabled { opacity: 0.55; cursor: default; }
.access-error { color: #fca5a5; }
</style>
