<script setup lang="ts">
import { toRef } from 'vue'
import type { BoardGroups } from './useBoardGroups'
import type { BoardGridSettings } from '../components/agent-board/boardGrid'
import type { ResizeEdge } from './groupGeometry'
import { useGroupFrameResize } from './useGroupFrameResize'
const props = defineProps<{ state: BoardGroups; grid: BoardGridSettings; point: (event: MouseEvent) => { x: number; y: number } }>()
const edges: ResizeEdge[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']
const { preview, start, move, finish, cancel } = useGroupFrameResize(props.state, toRef(props, 'grid'), props.point)
function bounds(group: { id: string; bounds: { x: number; y: number; width: number; height: number } }) {
  return preview.value?.id === group.id ? preview.value.bounds : group.bounds
}
</script>

<template>
  <div v-for="group in state.groups.value" :key="group.id" class="group-frame"
    :class="{ 'is-resizing': preview?.id === group.id }" :data-group-id="group.id"
    :style="{ left: `${bounds(group).x}px`, top: `${bounds(group).y}px`, width: `${bounds(group).width}px`, height: `${bounds(group).height}px` }">
    <button type="button" class="group-frame-label" @click.stop="state.activeId.value = group.id">
      {{ group.name }} <span>{{ group.members.length }} Agents · {{ group.tasks.filter(task => task.status === 'done').length }}/{{ group.tasks.length }}</span>
    </button>
    <div v-for="edge in edges" :key="edge" class="group-resize-handle" :class="`handle-${edge}`"
      :data-edge="edge" title="拖拽调整组范围，松开后更新成员；Esc 取消"
      @pointerdown.stop="start($event, group, edge)" @pointermove.stop="move"
      @pointerup.stop="finish" @pointercancel.stop="cancel" @lostpointercapture="cancel"
      @mousedown.stop @click.stop @dblclick.stop @contextmenu.prevent.stop />
  </div>
</template>

<style scoped>
.group-frame { position: absolute; z-index: 2; pointer-events: none; outline: 2px solid var(--text-accent); border-radius: 6px; background: color-mix(in srgb, var(--text-accent) 4%, transparent); box-sizing: border-box; }
.group-frame.is-resizing { outline-style: dashed; }
.group-frame-label { pointer-events: auto; position: absolute; bottom: calc(100% + 5px); left: 8px; max-width: calc(100% - 16px); display: flex; gap: 12px; align-items: center; border: 1px solid var(--border-color); background: var(--bg-primary); color: var(--text-primary); padding: 3px 9px; border-radius: 8px; cursor: pointer; white-space: nowrap; }
.group-frame-label span { color: var(--text-secondary); font-size: 11px; }
.group-resize-handle { position: absolute; pointer-events: auto; touch-action: none; }
.handle-n, .handle-s { left: 10px; right: 10px; height: 12px; cursor: ns-resize; }
.handle-n { top: -8px; } .handle-s { bottom: -8px; }
.handle-e, .handle-w { top: 10px; bottom: 10px; width: 12px; cursor: ew-resize; }
.handle-e { right: -8px; } .handle-w { left: -8px; }
.handle-ne, .handle-nw, .handle-se, .handle-sw { width: 14px; height: 14px; border-radius: 4px; }
.handle-ne, .handle-nw { top: -9px; } .handle-se, .handle-sw { bottom: -9px; }
.handle-ne, .handle-se { right: -9px; } .handle-nw, .handle-sw { left: -9px; }
.handle-ne, .handle-sw { cursor: nesw-resize; } .handle-nw, .handle-se { cursor: nwse-resize; }
.group-resize-handle:hover { background: color-mix(in srgb, var(--text-accent) 35%, transparent); }
</style>
