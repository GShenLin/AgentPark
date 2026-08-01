<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { listTools } from '../../api'
import {
  getAccessSettings,
  updateAccessSettings,
  type AccessPolicyData,
  type AccessPolicyUser,
} from '../../settingsApi'
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import FormCheckbox from '../FormCheckbox.vue'
import FormTextInput from '../FormTextInput.vue'

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const status = ref('')
const path = ref('')
const policy = ref<AccessPolicyData>({
  users: [],
  nonDeveloperFilteredTools: [],
})
const availableTools = ref<string[]>([])
const customTool = ref('')

const toolOptions = computed(() => Array.from(new Set([
  ...availableTools.value,
  ...policy.value.nonDeveloperFilteredTools,
])).sort((left, right) => left.localeCompare(right)))

async function load() {
  loading.value = true
  error.value = ''
  status.value = ''
  try {
    const [document, tools] = await Promise.all([getAccessSettings(), listTools()])
    path.value = document.path
    policy.value = {
      users: document.data.users.map((item) => ({
        ...item,
        clientIds: [...item.clientIds],
        ips: [...item.ips],
      })),
      nonDeveloperFilteredTools: [...document.data.nonDeveloperFilteredTools],
    }
    availableTools.value = tools
  } catch (cause: any) {
    error.value = String(cause?.message || cause)
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  status.value = ''
  try {
    const document = await updateAccessSettings(policy.value)
    path.value = document.path
    policy.value = {
      users: document.data.users.map((item) => ({
        ...item,
        clientIds: [...item.clientIds],
        ips: [...item.ips],
      })),
      nonDeveloperFilteredTools: [...document.data.nonDeveloperFilteredTools],
    }
    status.value = 'Saved'
  } catch (cause: any) {
    error.value = String(cause?.message || cause)
  } finally {
    saving.value = false
  }
}

function removeUser(username: string) {
  policy.value.users = policy.value.users.filter((item) => item.username !== username)
}

function addCustomTool() {
  const name = customTool.value.trim()
  if (!name) return
  if (!policy.value.nonDeveloperFilteredTools.some((item) => item.toLowerCase() === name.toLowerCase())) {
    policy.value.nonDeveloperFilteredTools.push(name)
  }
  customTool.value = ''
}

function toggleFilteredTool(tool: string, enabled: boolean) {
  const selected = policy.value.nonDeveloperFilteredTools
  policy.value.nonDeveloperFilteredTools = enabled
    ? Array.from(new Set([...selected, tool]))
    : selected.filter((item) => item !== tool)
}

function userKey(user: AccessPolicyUser) {
  return user.username.toLocaleLowerCase()
}

onMounted(load)
</script>

<template>
  <section class="access-settings">
    <header class="panel-head">
      <div>
        <h2>Authorization</h2>
        <p>远程用户首次访问时登记用户名和 IP；相同用户名的多台设备归属同一用户。Developer 保留节点配置的完整工具；其他用户在发送消息后过滤下方工具。</p>
        <code v-if="path">{{ path }}</code>
      </div>
      <div class="head-actions">
        <ActionButton compact :disabled="loading || saving" @click="load">Reload</ActionButton>
        <ActionButton variant="primary" compact :disabled="loading || saving" @click="save">
          {{ saving ? 'Saving…' : 'Save' }}
        </ActionButton>
      </div>
    </header>

    <div v-if="loading" class="hint">Loading authorization settings…</div>

    <section v-else class="group">
      <div class="group-title">
        <h3>Users</h3>
        <span>{{ policy.users.length }} registered user(s)</span>
      </div>
      <div v-if="!policy.users.length" class="hint">还没有远程访问记录。本机始终视为 Developer。</div>
      <article v-for="user in policy.users" :key="userKey(user)" class="user-row">
        <div class="user-main">
          <label>
            <span>Username</span>
            <FormTextInput v-model="user.username" maxlength="80" />
          </label>
          <label class="developer-toggle">
            <FormCheckbox v-model="user.developer" />
            <span>Developer</span>
          </label>
          <DangerButton @click="removeUser(user.username)">Delete</DangerButton>
        </div>
        <div class="user-meta">
          <span>Clients: {{ user.clientIds.join(', ') || 'unknown' }}</span>
          <span>IP: {{ user.ips.join(', ') || 'unknown' }}</span>
          <span>Last access: {{ user.lastSeenAt || 'unknown' }}</span>
        </div>
      </article>
    </section>

    <section v-if="!loading" class="group">
      <div class="group-title">
        <h3>Non-Developer filtered tools</h3>
        <span>{{ policy.nonDeveloperFilteredTools.length }} selected</span>
      </div>
      <div class="tool-grid">
        <label v-for="tool in toolOptions" :key="tool" class="tool-option">
          <FormCheckbox
            :model-value="policy.nonDeveloperFilteredTools.includes(tool)"
            @update:model-value="toggleFilteredTool(tool, $event)"
          />
          <span>{{ tool }}</span>
        </label>
      </div>
      <div class="custom-tool">
        <FormTextInput v-model="customTool" placeholder="Additional tool module or function name" @keyup.enter="addCustomTool" />
        <ActionButton compact @click="addCustomTool">Add</ActionButton>
      </div>
    </section>

    <div v-if="status" class="status">{{ status }}</div>
    <div v-if="error" class="error">{{ error }}</div>
  </section>
</template>

<style scoped>
.access-settings { display: grid; gap: 18px; padding: 18px; overflow: auto; }
.panel-head, .group-title, .user-main, .head-actions, .custom-tool {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
h2, h3, p { margin: 0; }
.panel-head p { margin-top: 6px; color: #94a3b8; line-height: 1.5; }
code { display: block; margin-top: 8px; color: #7dd3fc; }
.group { display: grid; gap: 10px; padding: 14px; border: 1px solid rgba(148, 163, 184, 0.2); border-radius: 10px; }
.group-title span, .hint, .user-meta { color: #94a3b8; font-size: 12px; }
.user-row { display: grid; gap: 8px; padding: 12px; border-radius: 8px; background: rgba(15, 23, 42, 0.42); }
.user-main label:first-child { flex: 1; display: grid; gap: 4px; }
.developer-toggle { display: flex; gap: 6px; align-items: center; }
.user-meta { display: flex; flex-wrap: wrap; gap: 6px 18px; }
.tool-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 8px; }
.tool-option { display: flex; gap: 7px; align-items: center; }
.custom-tool input { flex: 1; }
.status { color: #86efac; }
.error { color: #fca5a5; }
@media (max-width: 760px) {
  .panel-head, .user-main { align-items: stretch; flex-direction: column; }
  .head-actions { align-self: flex-end; }
}
</style>
