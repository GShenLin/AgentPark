<script setup lang="ts">
import { ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  createdAt?: string
  defaultExpanded?: boolean
  deferred?: boolean
  loading?: boolean
}>(), {
  createdAt: '',
  defaultExpanded: false,
  deferred: false,
  loading: false,
})

const emit = defineEmits<{
  (event: 'requestLoad'): void
}>()

const expanded = ref(props.defaultExpanded)
const openAfterLoad = ref(false)

watch(
  () => props.deferred,
  (deferred) => {
    if (!deferred && openAfterLoad.value) {
      openAfterLoad.value = false
      expanded.value = true
    }
  },
)

function toggleMetadata() {
  if (!expanded.value && props.deferred) {
    if (props.loading) return
    openAfterLoad.value = true
    emit('requestLoad')
    return
  }
  expanded.value = !expanded.value
}
</script>

<template>
  <section class="metadata-disclosure" :class="{ expanded }">
    <button
      class="metadata-disclosure-head"
      type="button"
      :aria-expanded="expanded"
      @click="toggleMetadata"
    >
      <span class="metadata-disclosure-title">
        <span class="metadata-disclosure-caret">{{ expanded ? 'v' : '>' }}</span>
        <span>Metadata</span>
      </span>
      <span>{{ loading ? 'Loading…' : createdAt }}</span>
    </button>
    <div v-if="expanded" class="metadata-disclosure-content">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.metadata-disclosure { border: 1px solid rgba(148, 163, 184, 0.2); border-left: 4px solid rgba(167, 139, 250, 0.72); border-radius: 8px; background: rgba(76, 29, 149, 0.1); overflow: visible; }
.metadata-disclosure-head { position: sticky; top: 0; z-index: 20; width: 100%; border: 0; border-radius: 7px; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 7px 10px; background: rgba(46, 16, 101, 0.98); box-shadow: 0 4px 10px rgba(2, 6, 23, 0.24); color: rgba(226, 232, 240, 0.94); font-size: 12px; font-weight: 700; cursor: pointer; text-align: left; }
.metadata-disclosure.expanded .metadata-disclosure-head { border-bottom: 1px solid rgba(167, 139, 250, 0.22); border-radius: 7px 7px 0 0; }
.metadata-disclosure-head:hover { background: rgba(59, 7, 100, 0.98); }
.metadata-disclosure-title { display: inline-flex; align-items: center; gap: 8px; }
.metadata-disclosure-caret { width: 12px; color: rgba(196, 181, 253, 0.96); font: 11px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.metadata-disclosure-head > span:last-child { color: rgba(148, 163, 184, 0.9); font-size: 11px; font-weight: 400; }
.metadata-disclosure-content { min-width: 0; }
</style>
