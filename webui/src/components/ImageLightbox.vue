<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

defineProps<{
  open: boolean
  src: string
  alt?: string
}>()

const emit = defineEmits<{
  (event: 'close'): void
}>()

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div v-if="open && src" class="image-lightbox" role="dialog" aria-modal="true" @click.self="emit('close')">
      <button class="image-lightbox-close" type="button" aria-label="关闭图片预览" @click="emit('close')">×</button>
      <img class="image-lightbox-content" :src="src" :alt="alt || '图片预览'" />
    </div>
  </Teleport>
</template>

<style scoped>
.image-lightbox {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 24px 24px;
  background: rgba(2, 6, 23, 0.92);
  backdrop-filter: blur(4px);
}

.image-lightbox-content {
  display: block;
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 8px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.55);
}

.image-lightbox-close {
  position: absolute;
  top: 10px;
  right: 14px;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
  font-size: 28px;
  line-height: 32px;
  cursor: pointer;
}
</style>
