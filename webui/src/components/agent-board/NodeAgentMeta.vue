<script setup lang="ts">
defineProps<{
  mode?: string
  providerId?: string
}>()
</script>

<template>
  <div class="agent-meta">
    <span class="agent-tag">{{ mode || 'chat' }}</span>
    <span class="agent-tag">{{ providerId || 'provider unset' }}</span>
  </div>
</template>

<style scoped>
.agent-meta {
  padding: 0 12px;
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}

.agent-tag {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
}
</style>
