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
  type NodeDesktopView,
  type PetAvatarFrame,
  type PetAvatarSummary,
} from './api'
import PetContextMenu from './components/pet-avatar/PetContextMenu.vue'
import PetAvatarRenderer from './components/pet-avatar/PetAvatarRenderer.vue'
import { usePetAvatarWindow } from './composables/usePetAvatarWindow'
import './PetDesktopView.css'

const params = new URLSearchParams(window.location.search)
const viewId = String(params.get('view_id') || '').trim()
const initialOpenChat = params.get('open_chat') === '1'
const initialDraftPrefix = String(params.get('draft_prefix') || '')

const view = ref<NodeDesktopView | null>(null)
const avatar = ref<PetAvatarFrame | null>(null)
const loadedAvatarId = ref('')
const message = ref('')
const messageInput = ref<HTMLTextAreaElement | null>(null)
const loading = ref(false)
const sending = ref(false)
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
const bubbleOpen = computed(() => !!notificationBubbleText.value)
const petMenuLayoutOpen = computed(() => petMenuLayoutPrepared.value || showPetMenu.value)
const {
  chatOpen,
  hidePetWindow,
  onAvatarPointerDown,
  openChatPanel,
  syncPetWindowLayout,
} = usePetAvatarWindow({ viewId, menuOpen: showPetMenu, bubbleOpen, bubbleHeight: notificationBubbleHeight })
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

function applyAskHereDraft(payload: AskHerePayload) {
  const draftPrefix = String(payload?.draft_prefix || '')
  if (draftPrefix && !message.value.startsWith(draftPrefix)) {
    message.value = `${draftPrefix}${message.value}`
  }
  if (payload?.open_chat || draftPrefix) {
    openChatPanel()
    void nextTick(() => {
      const input = messageInput.value
      if (!input) return
      input.focus()
      const end = input.value.length
      input.setSelectionRange(end, end)
    })
  }
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
  if (!text || !view.value) return
  sending.value = true
  try {
    await sendNodeDesktopViewMessage(view.value.view_id, text)
    message.value = ''
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

function closePetMenu() {
  showPetMenu.value = false
  petMenuLayoutPrepared.value = false
}

function updatePetMenuPosition() {
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
}

async function openPetMenu(event: MouseEvent) {
  const clickScreenX = event.screenX
  const clickScreenY = event.screenY
  petMenuLeft.value = event.clientX
  petMenuTop.value = event.clientY
  petMenuLayoutPrepared.value = true
  await nextTick()
  try {
    const layoutResult = await syncPetWindowLayout({ menu: true })
    const layoutBounds = readPetWindowLayoutBounds(layoutResult)
    if (layoutBounds) {
      petMenuLeft.value = clickScreenX - layoutBounds.x
      petMenuTop.value = clickScreenY - layoutBounds.y
    }
  } catch (exc) {
    petMenuLayoutPrepared.value = false
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to open pet menu')
    return
  }
  showPetMenu.value = true
  await nextTick()
  updatePetMenuPosition()
  const hasCachedCatalog = avatarCatalog.value.length > 0
  const catalogRequest = loadAvatarCatalog({ force: hasCachedCatalog })
  if (hasCachedCatalog) {
    catalogRequest
      .then(() => updatePetMenuPosition())
      .catch((exc) => {
        error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to load pet avatars')
      })
    return
  }
  try {
    await catalogRequest
    updatePetMenuPosition()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc || 'Failed to load pet avatars')
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
  if (stopAskHereListener) {
    stopAskHereListener()
    stopAskHereListener = null
  }
  closeGraphStream()
  closeLiveStream()
})
</script>

<template>
  <main class="pet-shell" :class="[statusClass, { 'chat-open': chatOpen, 'menu-open': petMenuLayoutOpen, 'has-bubble': bubbleOpen && !chatOpen && !petMenuLayoutOpen }]" @contextmenu.prevent.stop="openPetMenu" @pointerdown="closePetMenu">
    <section v-if="notificationBubbleText && !chatOpen && !petMenuLayoutOpen" ref="notificationBubbleElement" class="pet-bubble" :class="{ live: !!liveText }">
      {{ notificationBubbleText }}
    </section>

    <section
      class="pet-avatar"
      :class="[statusClass, { 'with-avatar-pack': avatar }]"
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

    <section v-if="chatOpen" class="pet-panel">
      <header class="pet-drag-region pet-header">
        <div>
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
      <div v-if="panelMessageText" class="pet-output">{{ panelMessageText }}</div>
      <form class="pet-compose" @submit.prevent="sendMessage">
        <textarea
          ref="messageInput"
          v-model="message"
          :disabled="sending"
          placeholder="Message this node"
          rows="4"
          @keydown="onKeydown"
        ></textarea>
        <div class="pet-actions">
          <button type="button" @click="refreshView">Refresh</button>
          <button class="primary" type="submit" :disabled="sending || !message.trim()">
            {{ sending ? 'Sending' : 'Send' }}
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

