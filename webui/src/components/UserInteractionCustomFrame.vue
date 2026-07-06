<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { UserInteractionField } from '../api'

const props = defineProps<{
  field: UserInteractionField
  requestId: string
}>()

const emit = defineEmits<{
  submit: [values: Record<string, unknown>]
  change: [value: Record<string, unknown>]
  error: [message: string]
}>()

const frameEl = ref<HTMLIFrameElement | null>(null)

const BRIDGE_SCRIPT = `
(function () {
  function send(type, payload) {
    window.parent.postMessage(Object.assign({ type: type }, payload || {}), '*');
  }
  window.AGENTPARK_INTERACTION = {
    submit: function (values) { send('agentpark-interaction-submit', { values: values || {} }); },
    change: function (value) { send('agentpark-interaction-change', { value: value || {} }); },
    error: function (message) { send('agentpark-interaction-error', { message: String(message || '') }); }
  };
  window.addEventListener('error', function (event) {
    send('agentpark-interaction-error', { message: event.message || 'custom UI script error' });
  });
})();
`

const frameTitle = computed(() => `${props.field.label || '自定义交互'} - ${props.requestId}`)
const frameHeight = computed(() => `${Math.max(180, Math.min(Number(props.field.height || 360), 900))}px`)
const srcdoc = computed(() => {
  const closeScript = '<' + '/script>'
  const initialData = JSON.stringify(props.field.initial_data || {}).replace(/<\/script/gi, '<\\/script')
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
:root { color-scheme: dark; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; padding: 14px; color: rgba(248, 250, 252, 0.95); background: #020617; }
button, input, textarea, select { font: inherit; }
button { cursor: pointer; }
${props.field.css || ''}
</style>
<script>window.AGENTPARK_INITIAL_DATA = ${initialData};${closeScript}
<script>${BRIDGE_SCRIPT}${closeScript}
</head>
<body>
${props.field.html || ''}
<script>${props.field.js || ''}${closeScript}
</body>
</html>`
})

function onMessage(event: MessageEvent) {
  if (event.source !== frameEl.value?.contentWindow) return
  const data = event.data
  if (!data || typeof data !== 'object') return
  if (data.type === 'agentpark-interaction-submit') {
    emit('submit', data.values && typeof data.values === 'object' ? data.values : {})
  } else if (data.type === 'agentpark-interaction-change') {
    emit('change', data.value && typeof data.value === 'object' ? data.value : {})
  } else if (data.type === 'agentpark-interaction-error') {
    emit('error', String(data.message || '自定义交互页面报错'))
  }
}

window.addEventListener('message', onMessage)
onBeforeUnmount(() => window.removeEventListener('message', onMessage))
</script>

<template>
  <iframe
    ref="frameEl"
    class="interaction-custom-frame"
    sandbox="allow-scripts allow-forms"
    :title="frameTitle"
    :srcdoc="srcdoc"
    :style="{ height: frameHeight }"
  ></iframe>
</template>
