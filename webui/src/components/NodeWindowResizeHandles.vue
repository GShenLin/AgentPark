<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import type { NodeWindowBridge, NodeWindowResizeEdge } from '../nodeWindow'
import { createNodeWindowResize } from '../nodeWindowResize'

const props = defineProps<{ host: NodeWindowBridge }>()
const resize = createNodeWindowResize(props.host)
const edges: NodeWindowResizeEdge[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']
onMounted(() => window.addEventListener('blur', resize.cancel))
onBeforeUnmount(() => {
  resize.cancel()
  window.removeEventListener('blur', resize.cancel)
})
</script>

<template>
  <div class="window-resize-handles" data-node-window-interactive aria-hidden="true">
    <div v-for="edge in edges" :key="edge" class="window-resize-handle" :class="`resize-${edge}`"
      @pointerdown="resize.down(edge, $event)" @pointermove="resize.move" @pointerup="resize.up"
      @pointercancel="resize.up" @lostpointercapture="resize.up" @click.stop @contextmenu.stop.prevent />
  </div>
</template>

<style scoped>
.window-resize-handles { position: absolute; inset: 0; z-index: 20; pointer-events: none; }
.window-resize-handle { position: absolute; pointer-events: auto; touch-action: none; -webkit-app-region: no-drag; }
.resize-n, .resize-s { left: 18px; right: 18px; height: 12px; cursor: ns-resize; }
.resize-n { top: -6px; }
.resize-s { bottom: -6px; }
.resize-e, .resize-w { top: 18px; bottom: 18px; width: 12px; cursor: ew-resize; }
.resize-e { right: -6px; }
.resize-w { left: -6px; }
.resize-ne, .resize-nw, .resize-se, .resize-sw { width: 24px; height: 24px; }
.resize-ne, .resize-nw { top: -6px; }
.resize-se, .resize-sw { bottom: -6px; }
.resize-ne, .resize-se { right: -6px; }
.resize-nw, .resize-sw { left: -6px; }
.resize-nw, .resize-se { cursor: nwse-resize; }
.resize-ne, .resize-sw { cursor: nesw-resize; }
</style>
