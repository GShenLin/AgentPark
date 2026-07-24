<script setup lang="ts">
import type { ParsedFilePatch } from '../utils/responseMetadataDiff'

defineProps<{ patches: ParsedFilePatch[] }>()

function lineNumber(value: number | undefined): string {
  return value === undefined ? '—' : String(value)
}
</script>

<template>
  <div class="file-diffs">
    <section v-for="(patch, patchIndex) in patches" :key="`${patch.path}-${patchIndex}`" class="file-diff">
      <header class="diff-header">
        <strong>{{ patch.path }}</strong>
        <span>{{ patch.operation.replace(/_/g, ' ') }}</span>
      </header>
      <div v-if="!patch.hunks.length" class="diff-empty">No line-level changes were included in the provider metadata.</div>
      <section v-for="(hunk, hunkIndex) in patch.hunks" :key="hunkIndex" class="diff-hunk">
        <div class="hunk-title">
          <span>{{ hunk.header || 'Changed lines' }}</span>
          <small v-if="!hunk.hasLineNumbers">The patch did not include source line numbers.</small>
        </div>
        <div class="diff-columns">
          <div class="column-label">Before · {{ patch.path }}</div>
          <div class="column-label">After · {{ patch.path }}</div>
        </div>
        <div v-for="(row, rowIndex) in hunk.rows" :key="rowIndex" class="diff-row">
          <div :class="['diff-cell', row.before?.kind === 'removed' && 'removed', !row.before && 'empty']">
            <span class="line-number">{{ lineNumber(row.before?.lineNumber) }}</span>
            <span class="line-marker">{{ row.before?.kind === 'removed' ? '−' : ' ' }}</span>
            <code>{{ row.before?.text ?? '' }}</code>
          </div>
          <div :class="['diff-cell', row.after?.kind === 'added' && 'added', !row.after && 'empty']">
            <span class="line-number">{{ lineNumber(row.after?.lineNumber) }}</span>
            <span class="line-marker">{{ row.after?.kind === 'added' ? '+' : ' ' }}</span>
            <code>{{ row.after?.text ?? '' }}</code>
          </div>
        </div>
      </section>
    </section>
  </div>
</template>

<style scoped>
.file-diffs,
.file-diff,
.diff-hunk {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.file-diffs {
  font-size: var(--theme-panel-memory-panel-font-diff, 14px);
}

.file-diffs,
.file-diff {
  gap: 8px;
}

.diff-header,
.hunk-title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  overflow-wrap: anywhere;
}

.diff-header {
  color: rgba(226, 232, 240, 0.94);
  font-size: inherit;
}

.diff-header span,
.hunk-title,
.diff-empty {
  color: rgba(148, 163, 184, 0.9);
  font-size: inherit;
}

.diff-hunk {
  overflow: auto;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 7px;
  background: rgba(2, 6, 23, 0.34);
}

.hunk-title {
  min-width: 760px;
  padding: 5px 8px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

.diff-columns,
.diff-row {
  display: grid;
  grid-template-columns: minmax(380px, 1fr) minmax(380px, 1fr);
  min-width: 760px;
}

.column-label {
  padding: 7px 8px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  color: rgba(186, 230, 253, 0.84);
  font-size: inherit;
  font-weight: 700;
}

.column-label + .column-label,
.diff-cell + .diff-cell {
  border-left: 1px solid rgba(148, 163, 184, 0.14);
}

.diff-cell {
  display: grid;
  grid-template-columns: 42px 18px minmax(0, 1fr);
  min-height: 24px;
  color: rgba(203, 213, 225, 0.9);
  font-size: inherit;
  line-height: 24px;
}

.diff-cell.removed {
  background: rgba(127, 29, 29, 0.3);
}

.diff-cell.added {
  background: rgba(20, 83, 45, 0.3);
}

.diff-cell.empty {
  background: rgba(15, 23, 42, 0.3);
}

.line-number {
  padding-right: 7px;
  color: rgba(100, 116, 139, 0.9);
  text-align: right;
  user-select: none;
}

.line-marker {
  color: rgba(148, 163, 184, 0.8);
  text-align: center;
  user-select: none;
}

.diff-cell.removed .line-marker {
  color: rgba(252, 165, 165, 0.94);
}

.diff-cell.added .line-marker {
  color: rgba(134, 239, 172, 0.94);
}

.diff-cell code {
  padding-right: 8px;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  font: inherit;
}
</style>
