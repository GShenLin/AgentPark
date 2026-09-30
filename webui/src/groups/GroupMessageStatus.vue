<script setup lang="ts">
import type { GroupDelivery } from './groupApi'
defineProps<{ deliveries: GroupDelivery[] }>()
function label(item: GroupDelivery) {
  if (item.state === 'cancelled') return '已取消'
  if (item.last_error) return item.state === 'pending' ? '投递失败，等待重试' : '处理失败'
  if (item.state === 'delivered') return '已完成'
  return item.started_at ? '处理中' : '等待处理'
}
</script>
<template>
  <ul class="group-message-status" aria-label="成员处理状态">
    <li v-for="item in deliveries" :key="item.node_id" :class="{ failed: !!item.last_error }">
      <strong>{{ item.node_id }}</strong> · {{ label(item) }}<p v-if="item.last_error">{{ item.last_error }}</p>
    </li>
  </ul>
</template>
<style scoped>
.group-message-status { list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; font-size: 12px; color: var(--text-secondary); }
li { padding: 6px 10px; border: 1px solid var(--border-light); border-radius: 8px; }
.failed { color: var(--accent-red); } p { margin: 4px 0 0; overflow-wrap: anywhere; }
</style>
