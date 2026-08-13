<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  note?: string
}>()

const text = computed(() => String(props.note || '').trim())
</script>

<template>
  <div v-if="text" class="node-floating-note" :title="text">{{ text }}</div>
</template>

<style scoped>
.node-floating-note {
  position: absolute;
  z-index: 4;
  left: 0;
  bottom: calc(100% + 8px);
  width: 100%;
  max-height: 112px;
  overflow: hidden;
  padding: 9px 11px;
  border: 1px solid rgba(250, 204, 21, 0.45);
  border-radius: 9px;
  background: rgba(66, 52, 15, 0.94);
  color: rgba(254, 249, 195, 0.98);
  box-shadow: 0 8px 18px rgba(0, 0, 0, 0.24);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  pointer-events: none;
  box-sizing: border-box;
}
</style>
