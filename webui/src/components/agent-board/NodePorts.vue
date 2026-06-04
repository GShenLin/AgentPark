<script setup lang="ts">
defineProps<{
  endpointId: string
  inputNum: number
  outputNum: number
}>()

const emit = defineEmits<{
  completeLink: [endpointId: string, index: number, event: PointerEvent]
  startLink: [endpointId: string, index: number, event: PointerEvent]
}>()
</script>

<template>
  <div
    v-for="i in inputNum"
    :key="`in-${endpointId}-${i}`"
    class="port port-in"
    :style="{ top: `${((i - 0.5) * 100) / inputNum}%` }"
    @pointerup.stop="emit('completeLink', endpointId, i - 1, $event)"
  ></div>
  <div
    v-for="i in outputNum"
    :key="`out-${endpointId}-${i}`"
    class="port port-out"
    :style="{ top: `${((i - 0.5) * 100) / outputNum}%` }"
    @pointerdown.stop="emit('startLink', endpointId, i - 1, $event)"
  ></div>
</template>

<style scoped>
.port {
  width: 24px;
  height: 48px;
  position: absolute;
  transform: translateY(-50%);
  cursor: crosshair;
  z-index: 1;
}

.port::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: rgba(148, 163, 184, 0.9);
  transform: translate(-50%, -50%);
}

.port-in {
  left: -12px;
}

.port-out {
  right: -12px;
}
</style>
