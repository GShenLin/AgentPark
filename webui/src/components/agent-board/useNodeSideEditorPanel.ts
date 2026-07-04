import { computed, onBeforeUnmount, ref, watch, type ComputedRef } from 'vue'
import type { AgentBoardContext, NodeCard } from './context'

const CARD_WIDTH = 230
const PANEL_DEFAULT_WIDTH = 360
const PANEL_DEFAULT_HEIGHT = 620
const PANEL_MIN_WIDTH = 320
const PANEL_MAX_WIDTH = 760
const PANEL_MIN_HEIGHT = 360
const PANEL_GAP = 28
const PANEL_CANVAS_MARGIN = 20
const PANEL_CANVAS_EXPAND_PADDING = 160

type ResizeHandle = 'right' | 'left' | 'bottom' | 'bottom-right' | 'bottom-left'
type ResizeSession = {
  handle: ResizeHandle
  startX: number
  startY: number
  startWidth: number
  startHeight: number
  startLeft: number
}
type PanelPosition = { left: number; top: number }
type DragSession = {
  nodeId: string
  startX: number
  startY: number
  startLeft: number
  startTop: number
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

export function useNodeSideEditorPanel(ctx: AgentBoardContext, selectedNode: ComputedRef<NodeCard | null>) {
  const panelSize = ref({ width: PANEL_DEFAULT_WIDTH, height: PANEL_DEFAULT_HEIGHT })
  const panelPositionOverrides = ref<Record<string, PanelPosition>>({})
  const resizeSession = ref<ResizeSession | null>(null)
  const dragSession = ref<DragSession | null>(null)

  const boundedPanelSize = computed(() => {
    const maxWidth = Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, ctx.canvasWidth.value - PANEL_CANVAS_MARGIN * 2))
    const maxHeight = Math.max(PANEL_MIN_HEIGHT, ctx.canvasHeight.value - PANEL_CANVAS_MARGIN * 2)
    return {
      width: clamp(panelSize.value.width, PANEL_MIN_WIDTH, maxWidth),
      height: clamp(panelSize.value.height, PANEL_MIN_HEIGHT, maxHeight),
    }
  })

  function clampPanelPosition(position: PanelPosition, size = boundedPanelSize.value): PanelPosition {
    const maxLeft = Math.max(0, ctx.canvasWidth.value - size.width)
    const maxTop = Math.max(0, ctx.canvasHeight.value - size.height)
    return {
      left: clamp(position.left, 0, maxLeft),
      top: clamp(position.top, 0, maxTop),
    }
  }

  function ensureCanvasCoversPanel(position: PanelPosition, size = boundedPanelSize.value) {
    const desiredRight = position.left + size.width
    const desiredBottom = position.top + size.height
    const nextWidth = Math.max(ctx.canvasWidth.value, Math.ceil(desiredRight + PANEL_CANVAS_EXPAND_PADDING))
    const nextHeight = Math.max(ctx.canvasHeight.value, Math.ceil(desiredBottom + PANEL_CANVAS_EXPAND_PADDING))
    if (nextWidth !== ctx.canvasWidth.value) ctx.canvasWidth.value = nextWidth
    if (nextHeight !== ctx.canvasHeight.value) ctx.canvasHeight.value = nextHeight
  }

  function setPanelPositionOverride(nodeId: string, position: PanelPosition) {
    ensureCanvasCoversPanel(position)
    panelPositionOverrides.value = {
      ...panelPositionOverrides.value,
      [nodeId]: clampPanelPosition(position),
    }
  }

  const defaultPanelPlacement = computed<'right' | 'left'>(() => {
    const node = selectedNode.value
    if (!node) return 'right'
    const width = boundedPanelSize.value.width
    return node.ui.x + CARD_WIDTH + PANEL_GAP + width <= ctx.canvasWidth.value - PANEL_CANVAS_MARGIN ? 'right' : 'left'
  })

  const defaultPanelPosition = computed<PanelPosition>(() => {
    const node = selectedNode.value
    if (!node) return { left: 0, top: 0 }
    const { width, height } = boundedPanelSize.value
    const preferRight = defaultPanelPlacement.value === 'right'
    const left = preferRight
      ? node.ui.x + CARD_WIDTH + PANEL_GAP
      : Math.max(0, node.ui.x - width - PANEL_GAP)
    const maxTop = Math.max(0, ctx.canvasHeight.value - height)
    return {
      left,
      top: clamp(node.ui.y, 0, maxTop),
    }
  })

  const currentPanelPosition = computed<PanelPosition>(() => {
    const nodeId = selectedNode.value?.id
    if (!nodeId) return defaultPanelPosition.value
    const override = panelPositionOverrides.value[nodeId]
    return override ? clampPanelPosition(override) : defaultPanelPosition.value
  })

  const panelPlacement = computed<'right' | 'left'>(() => {
    const node = selectedNode.value
    if (!node) return 'right'
    const override = panelPositionOverrides.value[node.id]
    if (!override) return defaultPanelPlacement.value
    const { width } = boundedPanelSize.value
    const panelCenter = clampPanelPosition(override).left + width / 2
    const nodeCenter = node.ui.x + CARD_WIDTH / 2
    return panelCenter >= nodeCenter ? 'right' : 'left'
  })

  const panelStyle = computed(() => {
    if (!selectedNode.value) return { display: 'none' }
    const { width, height } = boundedPanelSize.value
    const position = currentPanelPosition.value
    return {
      left: `${position.left}px`,
      top: `${position.top}px`,
      width: `${width}px`,
      height: `${height}px`,
    }
  })

  const horizontalResizeHandle = computed<ResizeHandle>(() => (panelPlacement.value === 'right' ? 'right' : 'left'))
  const cornerResizeHandle = computed<ResizeHandle>(() => (panelPlacement.value === 'right' ? 'bottom-right' : 'bottom-left'))
  const isResizingPanel = computed(() => resizeSession.value !== null)
  const isDraggingPanel = computed(() => dragSession.value !== null)

  function resizeCursor(handle: ResizeHandle) {
    if (handle === 'bottom') return 'ns-resize'
    if (handle === 'left' || handle === 'right') return 'ew-resize'
    if (handle === 'bottom-left') return 'nesw-resize'
    return 'nwse-resize'
  }

  function stopPanelResize() {
    if (!resizeSession.value) return
    resizeSession.value = null
    window.removeEventListener('pointermove', onPanelResizeMove)
    window.removeEventListener('pointerup', stopPanelResize)
    window.removeEventListener('blur', stopPanelResize)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  function onPanelResizeMove(event: PointerEvent) {
    const session = resizeSession.value
    if (!session) return
    const nodeId = selectedNode.value?.id
    const scale = ctx.canvasScale.value || 1
    const dx = (event.clientX - session.startX) / scale
    const dy = (event.clientY - session.startY) / scale
    let nextWidth = session.startWidth
    let nextHeight = session.startHeight

    if (session.handle === 'right' || session.handle === 'bottom-right') {
      nextWidth = session.startWidth + dx
    } else if (session.handle === 'left' || session.handle === 'bottom-left') {
      nextWidth = session.startWidth - dx
    }

    if (session.handle === 'bottom' || session.handle === 'bottom-right' || session.handle === 'bottom-left') {
      nextHeight = session.startHeight + dy
    }

    const maxWidth = Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, ctx.canvasWidth.value - PANEL_CANVAS_MARGIN * 2))
    const maxHeight = Math.max(PANEL_MIN_HEIGHT, ctx.canvasHeight.value - PANEL_CANVAS_MARGIN * 2)
    const width = clamp(nextWidth, PANEL_MIN_WIDTH, maxWidth)
    const height = clamp(nextHeight, PANEL_MIN_HEIGHT, maxHeight)
    panelSize.value = { width, height }
    if (nodeId && panelPositionOverrides.value[nodeId] && (session.handle === 'left' || session.handle === 'bottom-left')) {
      const right = session.startLeft + session.startWidth
      setPanelPositionOverride(nodeId, {
        left: right - width,
        top: currentPanelPosition.value.top,
      })
    }
    event.preventDefault()
  }

  function startPanelResize(handle: ResizeHandle, event: PointerEvent) {
    if (event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()
    const size = boundedPanelSize.value
    const position = currentPanelPosition.value
    resizeSession.value = {
      handle,
      startX: event.clientX,
      startY: event.clientY,
      startWidth: size.width,
      startHeight: size.height,
      startLeft: position.left,
    }
    document.body.style.cursor = resizeCursor(handle)
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', onPanelResizeMove)
    window.addEventListener('pointerup', stopPanelResize)
    window.addEventListener('blur', stopPanelResize)
  }

  function isPanelDragTarget(target: EventTarget | null) {
    if (!(target instanceof HTMLElement)) return false
    return !target.closest('button, input, textarea, select, a, [role="button"], .resize-handle')
  }

  function stopPanelDrag() {
    if (!dragSession.value) return
    dragSession.value = null
    window.removeEventListener('pointermove', onPanelDragMove)
    window.removeEventListener('pointerup', stopPanelDrag)
    window.removeEventListener('blur', stopPanelDrag)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  function onPanelDragMove(event: PointerEvent) {
    const session = dragSession.value
    if (!session) return
    const scale = ctx.canvasScale.value || 1
    const dx = (event.clientX - session.startX) / scale
    const dy = (event.clientY - session.startY) / scale
    setPanelPositionOverride(session.nodeId, {
      left: session.startLeft + dx,
      top: session.startTop + dy,
    })
    event.preventDefault()
  }

  function startPanelDrag(event: PointerEvent) {
    if (event.button !== 0 || !isPanelDragTarget(event.target)) return
    const nodeId = selectedNode.value?.id
    if (!nodeId) return
    stopPanelResize()
    event.preventDefault()
    event.stopPropagation()
    const position = currentPanelPosition.value
    dragSession.value = {
      nodeId,
      startX: event.clientX,
      startY: event.clientY,
      startLeft: position.left,
      startTop: position.top,
    }
    document.body.style.cursor = 'move'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', onPanelDragMove)
    window.addEventListener('pointerup', stopPanelDrag)
    window.addEventListener('blur', stopPanelDrag)
  }

  watch(
    boundedPanelSize,
    (size) => {
      if (size.width !== panelSize.value.width || size.height !== panelSize.value.height) {
        panelSize.value = size
      }
    },
  )

  onBeforeUnmount(() => {
    stopPanelResize()
    stopPanelDrag()
  })

  return {
    panelStyle,
    panelPlacement,
    horizontalResizeHandle,
    cornerResizeHandle,
    isResizingPanel,
    isDraggingPanel,
    startPanelResize,
    startPanelDrag,
  }
}
