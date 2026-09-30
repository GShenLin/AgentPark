<template>
  <footer class="conversation-composer-dock" @pointerdown.stop @click.stop>
    <slot name="status" />
    <div class="conversation-composer-content"><slot /></div>
  </footer>
</template>

<style scoped>
.conversation-composer-dock { position: relative; flex: 0 0 auto; width: 100%; box-sizing: border-box; max-height: min(42%, 320px); overflow: auto; padding: 12px max(24px, calc((100% - 800px) / 2)) 20px; background: var(--theme-panel-node-side-editor-background-color, var(--bg-primary)); }
.conversation-composer-content { display: flex; align-items: flex-start; gap: 8px; min-width: 0; }
.conversation-composer-content > :deep(*) { flex: 1 1 auto; min-width: 0; }
.conversation-composer-content > :deep(.stop-btn) { flex: 0 0 auto; }
@media (max-width: 720px) { .conversation-composer-dock { padding: 8px 12px 12px; } }
</style>
