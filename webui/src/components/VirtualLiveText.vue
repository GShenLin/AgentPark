<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type ComponentPublicInstance } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import ActionButton from './ActionButton.vue'
import { t } from '../i18n'

const props = defineProps<{
  text: string
  wordWrap: boolean
  label: string
}>()
const emit = defineEmits<{
  copy: [text: string]
  save: [text: string]
}>()

// Keep the original text for export. Only the visible logical lines enter the DOM.
const lines = computed(() => props.text.split(/\r\n|\r|\n/))
const viewport = ref<HTMLElement | null>(null)
const lineHeight = ref(20)
const virtualizer = useVirtualizer(computed(() => ({
  count: lines.value.length,
  getScrollElement: () => viewport.value,
  // Unseen lines start at one row; measureElement replaces this estimate with
  // the browser's actual wrapped height as each line enters the viewport.
  estimateSize: () => lineHeight.value,
  overscan: 5,
  anchorTo: 'end' as const,
  followOnAppend: true,
  scrollEndThreshold: 16,
})))
const visibleLines = computed(() => virtualizer.value.getVirtualItems())
const totalHeight = computed(() => virtualizer.value.getTotalSize())

function measureLine(element: Element | ComponentPublicInstance | null) {
  if (element instanceof HTMLElement) virtualizer.value.measureElement(element)
}

function scrollToLatest() {
  virtualizer.value.scrollToEnd()
}

async function resetMeasurements() {
  const instance = virtualizer.value
  // Use the previous measured geometry: the DOM may already have reflowed at
  // the new width when ResizeObserver runs.
  const offset = instance.scrollOffset ?? 0
  const atEnd = instance.getTotalSize() - offset - (instance.scrollRect?.height ?? 0) < 16
  const anchor = instance.getVirtualItemForOffset(offset)
  instance.measure()
  await nextTick()
  if (atEnd) scrollToLatest()
  else if (anchor) instance.scrollToIndex(anchor.index, { align: 'start' })
}

let resizeObserver: ResizeObserver | undefined
onMounted(async () => {
  const element = viewport.value!
  let measuredWidth = element.clientWidth
  let measuredLineHeight = Number.parseFloat(getComputedStyle(element).lineHeight)
  lineHeight.value = measuredLineHeight
  virtualizer.value.measure()
  resizeObserver = new ResizeObserver(() => {
    const width = element.clientWidth
    const height = Number.parseFloat(getComputedStyle(element).lineHeight)
    if (width === measuredWidth && height === measuredLineHeight) return
    measuredWidth = width
    measuredLineHeight = height
    lineHeight.value = height
    void resetMeasurements()
  })
  resizeObserver.observe(element)
  // The adapter attaches its scroll element in a watcher after the ref mounts.
  await nextTick()
  scrollToLatest()
})
onBeforeUnmount(() => resizeObserver?.disconnect())

watch(() => props.wordWrap, resetMeasurements)
</script>

<template>
  <div class="virtual-live-text">
    <div class="log-actions">
      <ActionButton compact @click="emit('copy', text)">{{ t('memory.copyFullText') }}</ActionButton>
      <ActionButton compact @click="emit('save', text)">{{ t('memory.saveFullText') }}</ActionButton>
      <ActionButton compact @click="scrollToLatest">{{ t('memory.jumpToLatest') }}</ActionButton>
    </div>
    <div
      ref="viewport"
      class="log-viewport"
      :class="{ wrapped: wordWrap }"
      :style="{ height: `${totalHeight}px` }"
      tabindex="0"
      role="region"
      :aria-label="label"
    >
      <div class="log-spacer" :style="{ height: `${totalHeight}px` }">
        <div
          v-for="line in visibleLines"
          :key="line.index"
          :ref="measureLine"
          :data-index="line.index"
          class="log-line"
          :style="{ transform: `translateY(${line.start}px)` }"
        >{{ lines[line.index] }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.virtual-live-text {
  padding: 10px;
  color: inherit;
  min-width: 0;
}
.log-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.log-viewport {
  position: relative;
  max-height: 50vh;
  min-height: 1.55em;
  overflow: auto;
  overflow-anchor: none;
  scrollbar-gutter: stable;
  font: inherit;
  line-height: 1.55;
  white-space: pre;
}
.log-spacer {
  position: relative;
  width: 100%;
}
.log-line {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  min-height: 1.55em;
}
.wrapped .log-line {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
