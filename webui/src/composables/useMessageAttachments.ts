import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { resolveDroppedPaths } from './droppedPaths'
import { uploadFiles } from '../uploadApi'
import { hasBoardClipboardMarker } from '../components/agent-board/boardClipboardProtocol'
import type { MessageAttachment } from './messageAttachments'

export function useMessageAttachments(options: {
  text: Ref<string>; attachments: Ref<MessageAttachment[]>; context: () => string
  onError: (message: string) => void
}) {
  const uploads = ref(0)
  let generation = 0
  watch(options.context, () => { generation++; uploads.value = 0 }, { flush: 'sync' })
  onBeforeUnmount(() => { generation++ })

  async function receive(work: () => Promise<MessageAttachment[]>) {
    const captured = generation
    uploads.value++
    try {
      const files = await work()
      if (captured !== generation) return
      for (const file of files) {
        if (!options.attachments.value.some(item => item.path === file.path)) options.attachments.value.push(file)
      }
    } catch (error) {
      if (captured === generation) options.onError(error instanceof Error ? error.message : String(error))
    } finally { if (captured === generation) uploads.value-- }
  }

  function addFiles(files: File[]) {
    return receive(async () => (await uploadFiles(files, 'message-composer')).files)
  }
  function drop(event: DragEvent) {
    event.preventDefault(); event.stopPropagation()
    return receive(() => resolveDroppedPaths(event, 'message-composer-drop'))
  }
  function paste(event: ClipboardEvent) {
    const data = event.clipboardData
    if (hasBoardClipboardMarker(data)) {
      event.preventDefault()
      options.onError('请将复制的 Agent 节点粘贴到看板画布。')
      return
    }
    const items = Array.from(data?.items || []).filter(item => item.kind === 'file')
    const files = items.length ? items.map(item => item.getAsFile()) : Array.from(data?.files || [])
    if (!files.length) return
    event.preventDefault()
    if (files.some(file => !file)) { options.onError('无法读取剪贴板中的文件，请重新复制。'); return }
    const text = data?.getData('text/plain') || ''
    const textarea = event.target instanceof HTMLTextAreaElement ? event.target : null
    const start = textarea?.selectionStart ?? options.text.value.length
    const end = textarea?.selectionEnd ?? start
    options.text.value = options.text.value.slice(0, start) + text + options.text.value.slice(end)
    if (textarea) requestAnimationFrame(() => textarea.setSelectionRange(start + text.length, start + text.length))
    return addFiles(files as File[])
  }
  return { isUploading: computed(() => uploads.value > 0), addFiles, drop, paste,
    remove: (index: number) => options.attachments.value.splice(index, 1) }
}
