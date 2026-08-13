<script setup lang="ts">
import { computed } from 'vue'
import { formatBoardClockCountdown, useSharedBoardClockNow } from './boardClockCountdown'

const props = defineProps<{
  nextFireAt: unknown
  fallback?: string
}>()

const nowMs = useSharedBoardClockNow()
const displayText = computed(() => formatBoardClockCountdown(
  props.nextFireAt,
  nowMs.value,
  String(props.fallback || ''),
))
</script>

<template>
  <div class="node-message" :class="{ empty: !displayText }">
    {{ displayText || ' ' }}
  </div>
</template>
