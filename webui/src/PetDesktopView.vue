<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  getNodeDesktopView,
  getPetAvatar,
  graphEventsStreamUrl,
  listPetAvatars,
  nodeInstanceLiveStreamUrl,
  sendNodeDesktopViewMessage,
  updateNodeDesktopView,
  exitServer,
  type MessageEnvelope,
  type NodeDesktopView,
  type NodeDesktopViewPanelSize,
  type PetAvatarFrame,
  type PetAvatarSummary,
  type ResourceKind,
} from './api'
import PetContextMenu from './components/pet-avatar/PetContextMenu.vue'
import PetAvatarRenderer from './components/pet-avatar/PetAvatarRenderer.vue'
import { handleMarkdownCodeCopyClick } from './components/markdownCodeCopy'
import { renderMarkdownTextWithoutKatex } from './components/memoryMarkdown'
import { usePetAvatarWindow } from './composables/usePetAvatarWindow'
import { normalizePetPanelSize, usePetPanelResize } from './composables/usePetPanelResize'
import { uploadFiles, type UploadedFileItem } from './uploadApi'
import './PetDesktopView.css'

const params = new URLSearchParams(window.location.search)
const viewId = String(params.get('view_id') || '').trim()
const initialOpenChat = params.get('open_chat') === '1'
const initialDraftPrefix = String(params.get('draft_prefix') || '')
const DEFAULT_PANEL_SIZE: NodeDesktopViewPanelSize = { width: 340, height: 360 }

const view = ref<NodeDesktopView | null>(null)
const avatar = ref<PetAvatarFrame | null>(null)
const loadedAvatarId = ref('')
const message = ref('')
const messageInput = ref<HTMLTextAreaElement | null>(null)
const panelElement = ref<HTMLElement | null>(null)
const panelSize = ref<NodeDesktopViewPanelSize | null>({ ...DEFAULT_PANEL_SIZE })
const attachedFiles = ref<UploadedFileItem[]>([])
const loading = ref(false)
const sending = ref(false)
const uploadingFiles = ref(false)
const error = ref('')
const showPetMenu = ref(false)
const petMenuLayoutPrepared = ref(false)
const petMenuLeft = ref(0)
const petMenuTop = ref(0)
const loadingAvatars = ref(false)
const avatarCatalog = ref<PetAvatarSummary[]>([])
const notificationBubbleText = ref('')
const notificationBubbleElement = ref<HTMLElement | null>(null)
const notificationBubbleHeight = ref(0)
const AVATAR_CATALOG_TTL_MS = 30_000
let graphSource: EventSource | null = null
let liveSource: EventSource | null = null
let graphStreamKey = ''
let liveStreamKey = ''
let avatarCatalogLoadedAt = 0
let avatarCatalogRequest: Promise<PetAvatarSummary[]> | null = null
let stopAskHereListener: (() => void) | null = null

type AskHerePayload = {
  open_chat?: boolean
  draft_prefix?: string
  working_path?: string
}

type PetDesktopBridge = {
  onAskHere?: (callback: (payload: AskHerePayload) => void) => () => void
  openMainPage?: () => Promise<unknown>
  log?: (event: string, payload: Record<string, unknown>) => Promise<unknown>
}

type PetWindowBounds = {
  x: number
  y: number
  width: number
  height: number
}

type GraphStreamPayload = {
  event?: string
  avatar_id?: string
  node_id?: string
  node_instance_id?: string
  from_id?: string
  from_node?: string
}

function readPetWindowLayoutBounds(result: unknown): PetWindowBounds | null {
  if (!result || typeof result !== 'object') return null
  const bounds = (result as { bounds?: unknown }).bounds
  if (!bounds || typeof bounds !== 'object') return null
  const rawBounds = bounds as Record<string, unknown>
  const nextBounds = {
    x: Number(rawBounds.x),
    y: Number(rawBounds.y),
    width: Number(rawBounds.width),
    height: Number(rawBounds.height),
  }
  if (Object.values(nextBounds).every((value) => Number.isFinite(value))) return nextBounds
  throw new Error('Invalid pet window layout bounds')
}

const node = computed(() => view.value?.node || null)
const state = computed(() => String(node.value?.state || 'idle'))
const liveText = computed(() => String(view.value?.live?.text || '').trim())
const panelMessageText = computed(() => truncatePetMessage(liveText.value || String(node.value?.last_message || '').trim(), 600))
const panelMessageHtml = computed(() => renderMarkdownTextWithoutKatex(panelMessageText.value))
const notificationBubblePreview = computed(() => truncatePetMessage(notificationBubbleText.value, 180))
const bubbleOpen = computed(() => !!notificationBubbleText.value)
const petMenuLayoutOpen = computed(() => petMenuLayoutPrepared.value || showPetMenu.value)
const {
  chatOpen,
  collapsePetPanel,
  hidePetWindow,
  onAvatarPointerDown,
  openChatPanel,
  syncPetWindowLayout,
} = usePetAvatarWindow({
  viewId,
  menuOpen: showPetMenu,
  menuLayoutOpen: petMenuLayoutOpen,
  bubbleOpen,
  bubbleHeight: notificationBubbleHeight,
  panelSize,
})
const {
  isResizingPanel,
  panelStyle,
  startPanelResize,
} = usePetPanelResize({
  viewId,
  panelElement,
  panelSize,
  syncPetWindowLayout,
  persistPanelSize: persistPanelSizePreference,
})
const statusLabel = computed(() => {
  if (error.value) return 'Error'
  if (state.value === 'working') return 'Running'
  if (liveText.value) return 'Streaming'
  if (state.value === 'stop') return 'Stopped'
  return 'Idle'
})
const statusClass = computed(() => {
  if (error.value) return 'error'
  if (state.value === 'working') return 'working'
  if (state.value === 'stop') return 'stop'
  return 'idle'
})
const avatarState = computed(() => {
  if (error.value) return 'error'
  if (liveText.value) return 'speaking'
  if (state.value === 'working') return 'working'
  if (state.value === 'stop') return 'sleeping'
  return 'idle'
})
const validAvatars = computed(() => avatarCatalog.value.filter((item) => item.valid))
const selectedAvatarId = computed(() => String(view.value?.avatar_style || loadedAvatarId.value || '').trim())
const canSendMessage = computed(() => (
  !sending.value
  && !uploadingFiles.value
  && (!!message.value.trim() || attachedFiles.value.length > 0)
))

function isAvatarCatalogFresh() {
  return avatarCatalog.value.length > 0 && Date.now() - avatarCatalogLoadedAt < AVATAR_CATALOG_TTL_MS
}

function truncatePetMessage(text: string, maxLength: number) {
  const normalized = String(text || '').trim()
  if (!normalized) return ''
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength).trimEnd()}...` : normalized
}

function getPetDesktopBridge(): PetDesktopBridge | null {
  const bridge = (window as unknown as { agentParkPet?: PetDesktopBridge }).agentParkPet
  return bridge && typeof bridge === 'object' ? bridge : null
}

function serializeError(exc: unknown) {
  if (exc instanceof Error) {
    return {
      name: exc.name,
      message: exc.message,
      stack: exc.stack,
    }
  }
  return { message: String(exc || '') }
}

function logPetDiagnostic(event: string, payload: Record<string, unknown> = {}) {
  const bridge = getPetDesktopBridge()
  if (bridge && typeof bridge.log === 'function') {
    void bridge.log(event, payload).catch((exc) => {
      console.warn('[AgentParkPetRenderer] failed to write diagnostic log', exc)
    })
  }
  console.debug('[AgentParkPetRenderer]', event, payload)
}

function onPetWindowError(event: ErrorEvent) {
  logPetDiagnostic('window-error', {
    message: event.message,
    filename: event.filename,
    line: event.lineno,
    column: event.colno,
    error: serializeError(event.error),
  })
}

function onPetUnhandledRejection(event: PromiseRejectionEvent) {
  logPetDiagnostic('unhandled-rejection', {
    reason: serializeError(event.reason),
  })
}

function applyAskHereDraft(payload: AskHerePayload) {
  const draftPrefix = String(payload?.draft_prefix || '')
  if (draftPrefix && !message.value.startsWith(draftPrefix)) {
    message.value = `${draftPrefix}${message.value}`
  }
  if (payload?.open_chat || draftPrefix) {
    void openChatPanel().then(() => nextTick()).then(() => {
      const input = messageInput.value
      if (!input) return
      input.focus()
      const end = input.value.length
      input.setSelectionRange(end, end)
    })
  }
}

async function persistPanelSizePreference(size: NodeDesktopViewPanelSize) {
  if (!view.value) return
  view.value = { ...view.value, panel_size: { ...size } }
  await updateNodeDesktopView(view.value.view_id, { panel_size: size })
}

function applyPanelSizeFromView(nextView: NodeDesktopView) {
  if (isResizingPanel.value) return
  panelSize.value = normalizePetPanelSize(nextView.panel_size) || { ...DEFAULT_PANEL_SIZE }
}

function showNotificationBubble(text: string) {
  const nextText = String(text || '').trim()
  if (nextText) notificationBubbleText.value = nextText
}

function syncNotificationBubbleHeight() {
  if (!notificationBubbleText.value || chatOpen.value || petMenuLayoutOpen.value) {
    notificationBubbleHeight.value = 0
    return
  }
  void nextTick(() => {
    notificationBubbleHeight.value = Math.ceil(notificationBubbleElement.value?.offsetHeight || 0)
  })
}

async function loadAvatarCatalog(options: { force?: boolean } = {}) {
  if (!options.force && isAvatarCatalogFresh()) return avatarCatalog.value
  if (avatarCatalogRequest) return avatarCatalogRequest
  loadingAvatars.value = avatarCatalog.value.length === 0
  avatarCatalogRequest = listPetAvatars()
    .then((result) => {
      const avatars = result.avatars || []
      avatarCatalog.value = avatars
      avatarCatalogLoadedAt = Date.now()
      return avatars
    })
    .finally(() => {
      avatarCatalogRequest = null
      loadingAvatars.value = false
    })
  return avatarCatalogRequest
}

async function refreshView() {
  if (!viewId) {
    error.value = 'view_id is required'
    return
  }
  loading.value = true
  try {
    const hadView = !!view.value
    const previousLastMessage = String(view.value?.node?.last_message || '').trim()
    const nextView = await getNodeDesktopView(viewId)
    if (nextView.visible === false) {
      view.value = nextView
      if (await hidePetWindow(nextView.view_id)) return
      window.close()
      return
    }
    view.value = nextView
    applyPanelSizeFromView(nextView)
    const nextLastMessage = String(nextView.node?.last_message || '').trim()
    if (hadView && nextLastMessage && nextLastMessage !== previousLastMessage && !String(nextView.live?.text || '').trim()) {
      showNotificationBubble(nextLastMessage)
    }
    error.value = ''
    await syncAvatar()
    syncStreams()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to load node desktop view')
  } finally {
    loading.value = false
  }
}

async function resolveAvatarId() {
  const explicit = String(view.value?.avatar_style || '').trim()
  if (explicit) return explicit
  const catalog = await loadAvatarCatalog()
  return catalog.find((item) => item.valid)?.id || ''
}

async function syncAvatar(options: { force?: boolean } = {}) {
  const avatarId = await resolveAvatarId()
  if (!avatarId) {
    avatar.value = null
    loadedAvatarId.value = ''
    return
  }
  if (!options.force && loadedAvatarId.value === avatarId && avatar.value) return
  const result = await getPetAvatar(avatarId)
  avatar.value = result.avatar
  loadedAvatarId.value = avatarId
}

function closeGraphStream() {
  if (!graphSource) return
  graphSource.close()
  graphSource = null
  graphStreamKey = ''
}

function closeLiveStream() {
  if (!liveSource) return
  liveSource.close()
  liveSource = null
  liveStreamKey = ''
}

function graphEventTargetsCurrentNode(payload: GraphStreamPayload) {
  const current = view.value
  if (!current) return false
  const nodeId = String(current.node_id || '').trim()
  return [payload.node_id, payload.node_instance_id, payload.from_id, payload.from_node]
    .map((item) => String(item || '').trim())
    .includes(nodeId)
}

function graphEventTargetsCurrentAvatar(payload: GraphStreamPayload) {
  const avatarId = String(payload.avatar_id || '').trim()
  return !!avatarId && avatarId === selectedAvatarId.value
}

function syncStreams() {
  const current = view.value
  if (!current) return
  const nextGraphKey = String(current.graph_id || '').trim()
  const nextLiveKey = `${String(current.graph_id || '').trim()}\0${String(current.node_id || '').trim()}`

  if (graphStreamKey !== nextGraphKey) {
    closeGraphStream()
    graphStreamKey = nextGraphKey
    graphSource = new EventSource(graphEventsStreamUrl(current.graph_id))
    graphSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(String(event.data || '{}')) as GraphStreamPayload
        const eventName = String(payload.event || '').trim()
        if (!eventName) return
        if (eventName === 'pet_avatar_updated') {
          if (graphEventTargetsCurrentAvatar(payload)) void syncAvatar({ force: true })
          return
        }
        if (!graphEventTargetsCurrentNode(payload)) return
        void refreshView()
      } catch (exc) {
        error.value = exc instanceof Error ? exc.message : String(exc || 'Invalid graph event')
      }
    }
    graphSource.onerror = () => {
      error.value = 'Graph event stream disconnected'
    }
  }

  if (liveStreamKey !== nextLiveKey) {
    closeLiveStream()
    liveStreamKey = nextLiveKey
    liveSource = new EventSource(nodeInstanceLiveStreamUrl(current.node_id, current.graph_id))
    liveSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(String(event.data || '{}')) as Record<string, unknown>
        const nextLiveText = String(payload.live_message || '')
        const eventType = String(payload.event_type || '').trim()
        const eventData = typeof payload.event === 'object' && payload.event ? payload.event as Record<string, unknown> : undefined
        const doneText = eventType === 'node_message_done' ? String(eventData?.text || '').trim() : ''
        const activeView = view.value || current
        view.value = {
          ...activeView,
          live: {
            text: nextLiveText,
            trace_id: String(payload.trace_id || ''),
            updated_at: Number(payload.updated_at || 0),
            is_streaming: !!payload.is_streaming,
            version: Number(payload.version || 0),
            event_type: eventType,
            event: eventData,
            interactive_session_id: String(payload.interactive_session_id || ''),
          },
        }
        if (nextLiveText.trim()) showNotificationBubble(nextLiveText)
        else if (doneText) showNotificationBubble(doneText)
        if (eventType) void refreshView()
      } catch (exc) {
        error.value = exc instanceof Error ? exc.message : String(exc || 'Invalid live event')
      }
    }
    liveSource.onerror = () => {
      error.value = 'Node live stream disconnected'
    }
  }
}

async function sendMessage() {
  const text = message.value.trim()
  if ((!text && attachedFiles.value.length === 0) || !view.value || sending.value || uploadingFiles.value) return
  const files = [...attachedFiles.value]
  const payload = composePetPayload(text, files)
  sending.value = true
  try {
    await sendNodeDesktopViewMessage(view.value.view_id, payload)
    message.value = ''
    attachedFiles.value = []
    error.value = ''
    await refreshView()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to send message')
  } finally {
    sending.value = false
  }
}

async function hideView() {
  if (!view.value) return
  try {
    closePetMenu()
    if (await hidePetWindow(view.value.view_id)) {
      return
    }
    view.value = await updateNodeDesktopView(view.value.view_id, { visible: false })
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to close view')
  }
}

function guessResourceKind(item: UploadedFileItem): ResourceKind | 'file' {
  const kind = String(item.kind || '').trim().toLowerCase()
  if (kind === 'image' || kind === 'video' || kind === 'audio' || kind === 'doc' || kind === 'url') return kind
  const mime = String(item.mime || '').toLowerCase()
  if (mime.startsWith('image/')) return 'image'
  if (mime.startsWith('video/')) return 'video'
  if (mime.startsWith('audio/')) return 'audio'
  const lower = String(item.path || item.name || '').toLowerCase()
  if (/\.(png|jpg|jpeg|webp|gif|bmp|svg)$/.test(lower)) return 'image'
  if (/\.(mp4|mov|mkv|webm|avi|flv|m4v)$/.test(lower)) return 'video'
  if (/\.(mp3|wav|ogg|flac|m4a)$/.test(lower)) return 'audio'
  if (/\.(pdf|doc|docx|ppt|pptx|xls|xlsx|txt|md)$/.test(lower)) return 'doc'
  return 'file'
}

function composePetPayload(text: string, files: UploadedFileItem[]): string | MessageEnvelope {
  if (!files.length) return text
  const parts: MessageEnvelope['parts'] = []
  if (text) parts.push({ type: 'text', text })
  for (const file of files) {
    const uri = String(file.path || '').trim()
    if (!uri) continue
    parts.push({
      type: 'resource',
      resource: {
        uri,
        name: String(file.name || ''),
        kind: guessResourceKind(file),
        mime: String(file.mime || ''),
        source: 'pet_chat',
        metadata: {
          size: Number(file.size || 0),
        },
      },
    })
  }
  return parts.length ? { role: 'user', parts } : text
}

function clipboardImageFiles(event: ClipboardEvent): File[] {
  const items = Array.from(event.clipboardData?.items || [])
  return items
    .filter((item) => item.kind === 'file' && item.type.toLowerCase().startsWith('image/'))
    .map((item, index) => {
      const file = item.getAsFile()
      if (!(file instanceof File)) return null
      if (String(file.name || '').trim()) return file
      const mime = String(file.type || item.type || 'image/png')
      const ext = mime.split('/')[1]?.split('+')[0] || 'png'
      return new File([file], `pasted-image-${Date.now()}-${index + 1}.${ext}`, { type: mime })
    })
    .filter((file): file is File => file instanceof File)
}

async function onPasteMessage(event: ClipboardEvent) {
  const files = clipboardImageFiles(event)
  if (!files.length) return
  event.preventDefault()
  uploadingFiles.value = true
  error.value = ''
  try {
    const uploaded = await uploadFiles(files, 'pet-chat-paste')
    for (const item of uploaded.files || []) {
      if (!attachedFiles.value.some((existing) => existing.path === item.path)) {
        attachedFiles.value.push(item)
      }
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to paste image')
  } finally {
    uploadingFiles.value = false
  }
}

function removeAttachedFile(index: number) {
  attachedFiles.value.splice(index, 1)
}

function attachmentExtension(file: UploadedFileItem) {
  const value = String(file.path || file.name || '').split('?')[0]?.split('#')[0] || ''
  const idx = value.lastIndexOf('.')
  if (idx < 0 || idx === value.length - 1) return ''
  return value.slice(idx + 1).toLowerCase()
}

function isImageAttachment(file: UploadedFileItem) {
  const mime = String(file.mime || '').toLowerCase()
  return mime.startsWith('image/') || ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'svg'].includes(attachmentExtension(file))
}

function normalizeAttachmentUrlPath(value: string) {
  const normalized = String(value || '').replace(/\\/g, '/')
  const lower = normalized.toLowerCase()
  if (lower.startsWith('/memories/')) return normalized
  if (lower.startsWith('memories/')) return `/${normalized}`
  if (lower.startsWith('./memories/')) return `/${normalized.slice(2)}`
  const marker = '/memories/'
  const markerIdx = lower.indexOf(marker)
  if (markerIdx >= 0) return normalized.slice(markerIdx)
  return ''
}

function isWebUrl(value: string) {
  return /^(https?|ftp):\/\//i.test(String(value || '').trim())
}

function isSpecialInlineUrl(value: string) {
  const text = String(value || '').trim().toLowerCase()
  return text.startsWith('data:') || text.startsWith('blob:')
}

function attachmentPreviewHref(file: UploadedFileItem) {
  const raw = String(file.path || '').trim()
  if (!raw) return ''
  if (isSpecialInlineUrl(raw) || isWebUrl(raw)) return raw
  if (raw.startsWith('/api/files/raw')) return raw
  const staticPath = normalizeAttachmentUrlPath(raw)
  if (staticPath) return staticPath
  return `/api/files/raw?path=${encodeURIComponent(raw)}`
}

function closePetMenu() {
  if (showPetMenu.value || petMenuLayoutPrepared.value) {
    logPetDiagnostic('pet-menu-close', {
      showPetMenu: showPetMenu.value,
      petMenuLayoutPrepared: petMenuLayoutPrepared.value,
      chatOpen: chatOpen.value,
    })
  }
  showPetMenu.value = false
  petMenuLayoutPrepared.value = false
}

function updatePetMenuPosition() {
  const before = { left: petMenuLeft.value, top: petMenuTop.value }
  const width = 190
  const height = Math.min(260, 136 + Math.max(1, validAvatars.value.length) * 32)
  const margin = 8
  let maxTop = window.innerHeight - height - margin
  if (petMenuLayoutOpen.value && !chatOpen.value) {
    const avatarElement = document.querySelector<HTMLElement>('.pet-avatar')
    const avatarTop = avatarElement?.getBoundingClientRect().top
    if (Number.isFinite(avatarTop) && Number(avatarTop) >= height + margin * 2) {
      maxTop = Math.min(maxTop, Math.floor(Number(avatarTop) - height - margin))
    }
  }
  petMenuLeft.value = Math.max(margin, Math.min(petMenuLeft.value, window.innerWidth - width - margin))
  petMenuTop.value = Math.max(margin, Math.min(petMenuTop.value, maxTop))
  logPetDiagnostic('pet-menu-position', {
    before,
    after: { left: petMenuLeft.value, top: petMenuTop.value },
    viewport: { width: window.innerWidth, height: window.innerHeight },
    menu: { width, height, maxTop },
    avatars: validAvatars.value.length,
  })
}

async function openPetMenu(event: MouseEvent) {
  logPetDiagnostic('pet-menu-open-start', {
    button: event.button,
    client: { x: event.clientX, y: event.clientY },
    screen: { x: event.screenX, y: event.screenY },
    chatOpen: chatOpen.value,
    showPetMenu: showPetMenu.value,
    petMenuLayoutPrepared: petMenuLayoutPrepared.value,
    window: { width: window.innerWidth, height: window.innerHeight },
  })
  if (chatOpen.value) {
    collapsePetPanel()
    logPetDiagnostic('pet-menu-open-collapsed-chat')
  }
  const clickScreenX = event.screenX
  const clickScreenY = event.screenY
  petMenuLeft.value = event.clientX
  petMenuTop.value = event.clientY
  petMenuLayoutPrepared.value = true
  await nextTick()
  logPetDiagnostic('pet-menu-layout-request', {
    left: petMenuLeft.value,
    top: petMenuTop.value,
    petMenuLayoutPrepared: petMenuLayoutPrepared.value,
  })
  try {
    const layoutResult = await syncPetWindowLayout({ expanded: false, menu: true, bubble: false })
    logPetDiagnostic('pet-menu-layout-result', {
      layoutResult: layoutResult && typeof layoutResult === 'object' ? layoutResult as Record<string, unknown> : { value: layoutResult },
      clickScreen: { x: clickScreenX, y: clickScreenY },
      window: { width: window.innerWidth, height: window.innerHeight },
    })
    const layoutBounds = readPetWindowLayoutBounds(layoutResult)
    if (layoutBounds) {
      petMenuLeft.value = clickScreenX - layoutBounds.x
      petMenuTop.value = clickScreenY - layoutBounds.y
    }
  } catch (exc) {
    petMenuLayoutPrepared.value = false
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to open pet menu')
    logPetDiagnostic('pet-menu-layout-error', {
      error: serializeError(exc),
      displayedError: error.value,
    })
    return
  }
  showPetMenu.value = true
  await nextTick()
  logPetDiagnostic('pet-menu-visible', {
    left: petMenuLeft.value,
    top: petMenuTop.value,
    window: { width: window.innerWidth, height: window.innerHeight },
  })
  updatePetMenuPosition()
  const hasCachedCatalog = avatarCatalog.value.length > 0
  const catalogRequest = loadAvatarCatalog({ force: hasCachedCatalog })
  logPetDiagnostic('pet-menu-avatar-catalog-request', {
    hasCachedCatalog,
    cachedCount: avatarCatalog.value.length,
  })
  if (hasCachedCatalog) {
    catalogRequest
      .then(() => {
        logPetDiagnostic('pet-menu-avatar-catalog-loaded', {
          count: avatarCatalog.value.length,
          validCount: validAvatars.value.length,
        })
        updatePetMenuPosition()
      })
      .catch((exc) => {
        error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to load pet avatars')
        logPetDiagnostic('pet-menu-avatar-catalog-error', {
          error: serializeError(exc),
          displayedError: error.value,
        })
      })
    return
  }
  try {
    await catalogRequest
    logPetDiagnostic('pet-menu-avatar-catalog-loaded', {
      count: avatarCatalog.value.length,
      validCount: validAvatars.value.length,
    })
    updatePetMenuPosition()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to load pet avatars')
    logPetDiagnostic('pet-menu-avatar-catalog-error', {
      error: serializeError(exc),
      displayedError: error.value,
    })
  }
}

async function changeAvatar(avatarId: string) {
  const safeAvatarId = String(avatarId || '').trim()
  if (!view.value || !safeAvatarId) return
  try {
    view.value = await updateNodeDesktopView(view.value.view_id, { avatar_style: safeAvatarId })
    loadedAvatarId.value = ''
    await syncAvatar()
    avatarCatalogLoadedAt = 0
    closePetMenu()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to change avatar')
  }
}

async function openMainPage() {
  const bridge = getPetDesktopBridge()
  if (!bridge || typeof bridge.openMainPage !== 'function') {
    error.value = 'Pet bridge openMainPage is unavailable'
    return
  }
  try {
    await bridge.openMainPage()
    closePetMenu()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to open main page')
  }
}

async function closeAll() {
  try {
    closePetMenu()
    await exitServer()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to close AgentPark')
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  void sendMessage()
}

onMounted(() => {
  document.documentElement.classList.add('pet-transparent-root')
  document.body.classList.add('pet-transparent-root')
  window.addEventListener('error', onPetWindowError)
  window.addEventListener('unhandledrejection', onPetUnhandledRejection)
  logPetDiagnostic('mounted', {
    viewId,
    initialOpenChat,
    hasInitialDraftPrefix: !!initialDraftPrefix,
    window: { width: window.innerWidth, height: window.innerHeight },
  })
  if (initialOpenChat || initialDraftPrefix) {
    applyAskHereDraft({ open_chat: initialOpenChat, draft_prefix: initialDraftPrefix })
  }
  const bridge = getPetDesktopBridge()
  if (bridge && typeof bridge.onAskHere === 'function') {
    stopAskHereListener = bridge.onAskHere((payload) => applyAskHereDraft(payload))
  }
  void refreshView()
  void syncPetWindowLayout()
  void loadAvatarCatalog().catch((exc) => {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to load pet avatars')
  })
})

watch(chatOpen, (isOpen) => {
  if (isOpen) notificationBubbleText.value = ''
})

watch([notificationBubbleText, chatOpen, showPetMenu, petMenuLayoutPrepared], syncNotificationBubbleHeight, { flush: 'post' })

onBeforeUnmount(() => {
  document.documentElement.classList.remove('pet-transparent-root')
  document.body.classList.remove('pet-transparent-root')
  window.removeEventListener('error', onPetWindowError)
  window.removeEventListener('unhandledrejection', onPetUnhandledRejection)
  if (stopAskHereListener) {
    stopAskHereListener()
    stopAskHereListener = null
  }
  closeGraphStream()
  closeLiveStream()
})
</script>

<template>
  <main class="pet-shell" :class="[statusClass, { 'chat-open': chatOpen, 'menu-open': petMenuLayoutOpen, 'has-bubble': bubbleOpen && !chatOpen && !petMenuLayoutOpen }]" @pointerdown="closePetMenu">
    <section v-if="notificationBubbleText && !chatOpen && !petMenuLayoutOpen" ref="notificationBubbleElement" class="pet-bubble" :class="{ live: !!liveText }">
      <span class="pet-bubble-text">{{ notificationBubblePreview }}</span>
    </section>

    <section
      class="pet-avatar"
      :class="[statusClass, { 'with-avatar-pack': avatar }]"
      @contextmenu.prevent.stop="openPetMenu"
      @pointerdown.stop="onAvatarPointerDown"
      @dragstart.prevent
    >
      <PetAvatarRenderer v-if="avatar" :avatar="avatar" :state="avatarState" display-mode="natural" />
      <div v-else class="pet-face">
        <span class="pet-eye left"></span>
        <span class="pet-eye right"></span>
        <span class="pet-mouth"></span>
      </div>
    </section>

    <section v-if="chatOpen" ref="panelElement" class="pet-panel" :style="panelStyle">
      <div class="pet-panel-resize pet-panel-resize-top" @pointerdown="startPanelResize('top', $event)"></div>
      <div class="pet-panel-resize pet-panel-resize-right" @pointerdown="startPanelResize('right', $event)"></div>
      <div class="pet-panel-resize pet-panel-resize-bottom" @pointerdown="startPanelResize('bottom', $event)"></div>
      <div class="pet-panel-resize pet-panel-resize-left" @pointerdown="startPanelResize('left', $event)"></div>
      <div class="pet-panel-resize pet-panel-resize-top-left" @pointerdown="startPanelResize('top-left', $event)"></div>
      <div class="pet-panel-resize pet-panel-resize-top-right" @pointerdown="startPanelResize('top-right', $event)"></div>
      <div class="pet-panel-resize pet-panel-resize-bottom-right" @pointerdown="startPanelResize('bottom-right', $event)"></div>
      <div class="pet-panel-resize pet-panel-resize-bottom-left" @pointerdown="startPanelResize('bottom-left', $event)"></div>
      <header class="pet-header">
        <div class="pet-header-drag-region">
          <div class="pet-title">{{ node?.name || view?.node_id || 'Node' }}</div>
          <div class="pet-meta">{{ view?.graph_id || 'graph' }} / {{ view?.node_id || 'node' }}</div>
        </div>
        <button class="pet-icon-button" type="button" title="Close" @click="hideView">x</button>
      </header>
      <div class="pet-status-row">
        <span class="pet-status" :class="statusClass"></span>
        <span>{{ statusLabel }}</span>
        <span v-if="node?.pending_count" class="pet-count">{{ node.pending_count }}</span>
      </div>
      <div
        v-if="panelMessageText"
        class="pet-output markdown-body"
        v-html="panelMessageHtml"
        @click="handleMarkdownCodeCopyClick"
      ></div>
      <form class="pet-compose" @submit.prevent="sendMessage">
        <textarea
          ref="messageInput"
          v-model="message"
          :disabled="sending"
          placeholder="Message this node"
          rows="4"
          @keydown="onKeydown"
          @paste="onPasteMessage"
        ></textarea>
        <div v-if="attachedFiles.length || uploadingFiles" class="pet-attachments">
          <div
            v-for="(file, index) in attachedFiles"
            :key="file.path"
            class="pet-attachment"
            :class="{ image: isImageAttachment(file) }"
          >
            <a
              v-if="isImageAttachment(file) && attachmentPreviewHref(file)"
              class="pet-attachment-thumb"
              :href="attachmentPreviewHref(file)"
              target="_blank"
              rel="noreferrer"
              :title="file.path"
            >
              <img :src="attachmentPreviewHref(file)" :alt="file.name" loading="lazy" />
            </a>
            <span class="pet-attachment-name" :title="file.path">{{ file.name || file.path }}</span>
            <button type="button" class="pet-attachment-remove" :disabled="sending" @click="removeAttachedFile(index)">x</button>
          </div>
          <span v-if="uploadingFiles" class="pet-uploading">Uploading...</span>
        </div>
        <div class="pet-actions">
          <button type="button" @click="refreshView">Refresh</button>
          <button class="primary" type="submit" :disabled="!canSendMessage">
            {{ sending ? 'Sending' : uploadingFiles ? 'Uploading' : 'Send' }}
          </button>
        </div>
      </form>
      <div v-if="error" class="pet-error">{{ error }}</div>
    </section>
    <PetContextMenu
      v-if="showPetMenu"
      :left="petMenuLeft"
      :top="petMenuTop"
      :loading="loadingAvatars"
      :avatars="validAvatars"
      :selected-avatar-id="selectedAvatarId"
      @open-main-page="openMainPage"
      @close="hideView"
      @close-all="closeAll"
      @change-avatar="changeAvatar"
    />
  </main>
</template>

