<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { listRemoteWorkers, type RegisteredRemoteWorker } from '../../remoteWorkerApi'

const workers = ref<RegisteredRemoteWorker[]>([])
const error = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let disposed = false
let loading = false
async function load() {
  if (loading) return
  loading = true
  try {
    const result = await listRemoteWorkers()
    if (!disposed) { workers.value = result; error.value = '' }
  } catch (cause) { if (!disposed) error.value = String(cause) }
  finally { loading = false }
}
onMounted(() => { void load(); timer = setInterval(load, 5000) })
onUnmounted(() => { disposed = true; clearInterval(timer) })
</script>
<template>
  <section class="remote-workers">
    <header><h4>远程执行设备</h4><button @click="load">刷新</button></header>
    <p>已通过同一鉴权中心审核的在线 AgentPark 和 Remote 都可作为执行设备。节点右键 → LinkToRemote 即可选择。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="!workers.length && !error">暂无登记的远程执行设备。</p>
    <article v-for="worker in workers" :key="worker.worker_id">
      <strong>{{ worker.display_name }}</strong> · {{ worker.online ? '在线' : '离线' }}
      <p>{{ worker.connection_kind === 'direct' ? '登记在当前 AgentPark' : '通过鉴权中心发现' }} · {{ worker.host_kind }}</p>
      <p>默认工作目录：{{ worker.workspace_path }}</p>
      <details><summary>设备信息</summary><code>{{ worker.worker_id }}</code><p>{{ worker.capabilities.join('、') }}</p></details>
    </article>
  </section>
</template>
<style scoped>
.remote-workers { display: grid; gap: 12px; } header { display: flex; justify-content: space-between; align-items: center; }
h4, p { margin: 0; } article { border: 1px solid #8886; border-radius: 8px; padding: 14px; }
article p { margin: 8px 0; } code { overflow-wrap: anywhere; } [role=alert] { color: #e56b6b; }
</style>
