import { ref } from 'vue'
import { listFiles, saveFile } from '../api'
import { useGlobalState } from './useGlobalState'

const WINDOWS_INVALID_FILENAME = /[<>:"/\\|?*\x00-\x1F]/

function defaultMarkdownFilename() {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-')
  return `memory-${stamp}`
}

function normalizeMarkdownFilename(value: string) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  return raw.toLowerCase().endsWith('.md') ? raw.slice(0, -3) : raw
}

function validateMarkdownFilename(value: string): string | null {
  const name = normalizeMarkdownFilename(value)
  if (!name) return '请输入文件名。'
  if (name === '.' || name === '..') return '文件名不能是 . 或 ..。'
  if (WINDOWS_INVALID_FILENAME.test(name)) return '文件名不能包含路径分隔符或 Windows 非法字符。'
  if (/[. ]$/.test(name)) return '文件名不能以空格或点结尾。'
  return null
}

function joinPath(baseDir: string, filename: string) {
  const base = String(baseDir || '').trim()
  if (!base) return filename
  const separator = base.includes('\\') || /^[a-zA-Z]:/.test(base) ? '\\' : '/'
  return `${base.replace(/[\\/]+$/, '')}${separator}${filename}`
}

function copyTextWithSelectionFallback(text: string) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'true')
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.left = '0'
  textarea.style.width = '1px'
  textarea.style.height = '1px'
  textarea.style.opacity = '0'
  textarea.style.pointerEvents = 'none'
  document.body.appendChild(textarea)

  const selection = document.getSelection()
  const previousRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null
  textarea.focus({ preventScroll: true })
  textarea.select()
  textarea.setSelectionRange(0, textarea.value.length)

  try {
    const copied = document.execCommand('copy')
    if (!copied) throw new Error('Copy command was rejected.')
  } finally {
    document.body.removeChild(textarea)
    if (selection) {
      selection.removeAllRanges()
      if (previousRange) selection.addRange(previousRange)
    }
  }
}

export function useMemoryMessageExport() {
  const { graphSnapshot, selectedNodeId, lastError } = useGlobalState()

  const saveDialogOpen = ref(false)
  const saveDialogFilename = ref('')
  const saveDialogTargetDir = ref('')
  const saveDialogError = ref<string | null>(null)
  const saveDialogSaving = ref(false)
  const pendingSaveText = ref('')

  function selectedNodeWorkingPath() {
    const nodeId = String(selectedNodeId.value || '').trim()
    const nodes = Array.isArray(graphSnapshot.value?.nodes) ? graphSnapshot.value.nodes : []
    const node = nodes.find((item) => item.id === nodeId)
    return String(node?.workingPath || '').trim()
  }

  async function resolveSaveTargetDir() {
    const fromNode = selectedNodeWorkingPath()
    if (fromNode) return fromNode
    const listed = await listFiles()
    return String(listed.current_path || '').trim()
  }

  async function openSaveMessageDialog(text: string) {
    const payload = String(text || '')
    if (!payload.trim()) {
      lastError.value = 'No text content to save.'
      return
    }
    pendingSaveText.value = payload
    saveDialogFilename.value = defaultMarkdownFilename()
    saveDialogError.value = null
    saveDialogTargetDir.value = ''
    saveDialogOpen.value = true
    try {
      saveDialogTargetDir.value = await resolveSaveTargetDir()
      if (!saveDialogTargetDir.value) {
        saveDialogError.value = '无法解析当前项目路径。'
      }
    } catch (e: any) {
      saveDialogError.value = String(e?.message || e)
    }
  }

  async function copyMessageText(text: string) {
    const payload = String(text || '')
    if (!payload.trim()) {
      lastError.value = 'No text content to copy.'
      return
    }
    try {
      if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(payload)
      } else {
        copyTextWithSelectionFallback(payload)
      }
    } catch (e: any) {
      lastError.value = `Failed to copy message: ${String(e?.message || e)}`
    }
  }

  function cancelSaveMessageDialog() {
    saveDialogOpen.value = false
    saveDialogSaving.value = false
    saveDialogError.value = null
    pendingSaveText.value = ''
  }

  async function confirmSaveMessageDialog() {
    const validationError = validateMarkdownFilename(saveDialogFilename.value)
    if (validationError) {
      saveDialogError.value = validationError
      return
    }
    if (!saveDialogTargetDir.value) {
      saveDialogError.value = '无法解析当前项目路径。'
      return
    }

    const baseName = normalizeMarkdownFilename(saveDialogFilename.value)
    const targetPath = joinPath(saveDialogTargetDir.value, `${baseName}.md`)
    saveDialogSaving.value = true
    saveDialogError.value = null
    try {
      await saveFile(targetPath, pendingSaveText.value)
      cancelSaveMessageDialog()
    } catch (e: any) {
      saveDialogError.value = String(e?.message || e)
    } finally {
      saveDialogSaving.value = false
    }
  }

  return {
    saveDialogOpen,
    saveDialogFilename,
    saveDialogTargetDir,
    saveDialogError,
    saveDialogSaving,
    openSaveMessageDialog,
    confirmSaveMessageDialog,
    cancelSaveMessageDialog,
    copyMessageText,
  }
}
