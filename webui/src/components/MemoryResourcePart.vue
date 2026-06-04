<script setup lang="ts">
defineProps<{
  part: Record<string, unknown>
}>()

type ResourcePayload = {
  uri: string
  kind: string
  name: string
  mime: string
}

function resourcePayload(part: Record<string, unknown>): ResourcePayload {
  const resource = part && typeof part === 'object' ? (part as any).resource : null
  if (!resource || typeof resource !== 'object') {
    return { uri: '', kind: 'file', name: '', mime: '' }
  }
  return {
    uri: String((resource as any).uri || '').trim(),
    kind: String((resource as any).kind || 'file').trim().toLowerCase() || 'file',
    name: String((resource as any).name || '').trim(),
    mime: String((resource as any).mime || '').trim().toLowerCase(),
  }
}

function resourceExtension(value: string) {
  const q = String(value || '').split('?')[0] || ''
  const path = q.split('#')[0] || ''
  const idx = path.lastIndexOf('.')
  if (idx < 0 || idx === path.length - 1) return ''
  return path.slice(idx + 1).toLowerCase()
}

function resourceLabel(part: Record<string, unknown>) {
  const payload = resourcePayload(part)
  return payload.kind || 'file'
}

function resourceDisplayName(part: Record<string, unknown>) {
  const payload = resourcePayload(part)
  if (payload.name) return payload.name
  if (!payload.uri) return ''
  const normalized = payload.uri.replace(/\\/g, '/')
  const chunks = normalized.split('/')
  return chunks[chunks.length - 1] || payload.uri
}

function normalizeResourceUrlPath(value: string) {
  const normalized = String(value || '').replace(/\\/g, '/')
  const lower = normalized.toLowerCase()
  if (lower.startsWith('/memories/')) return normalized
  if (lower.startsWith('memories/')) return `/${normalized}`
  if (lower.startsWith('./memories/')) return `/${normalized.slice(2)}`
  const marker = '/memories/'
  const markerIdx = lower.indexOf(marker)
  if (markerIdx >= 0) {
    return normalized.slice(markerIdx)
  }
  return ''
}

function isWebUrl(value: string) {
  return /^(https?|ftp):\/\//i.test(String(value || '').trim())
}

function isSpecialInlineUrl(value: string) {
  const text = String(value || '').trim().toLowerCase()
  return text.startsWith('data:') || text.startsWith('blob:')
}

function resolveResourceHref(uri: string, download = false) {
  const raw = String(uri || '').trim()
  if (!raw) return ''
  if (isSpecialInlineUrl(raw) || isWebUrl(raw)) return raw
  if (raw.startsWith('/api/files/raw')) return raw
  const staticPath = normalizeResourceUrlPath(raw)
  if (staticPath) return staticPath
  const base = `/api/files/raw?path=${encodeURIComponent(raw)}`
  return download ? `${base}&download=1` : base
}

function resourcePreviewHref(part: Record<string, unknown>) {
  const payload = resourcePayload(part)
  return resolveResourceHref(payload.uri, false)
}

function resourceDownloadHref(part: Record<string, unknown>) {
  const payload = resourcePayload(part)
  return resolveResourceHref(payload.uri, true)
}

function resourceCanPreviewImage(part: Record<string, unknown>) {
  const payload = resourcePayload(part)
  const ext = resourceExtension(payload.uri)
  if (payload.kind === 'image') return true
  if (payload.mime.startsWith('image/')) return true
  return ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'svg'].includes(ext)
}

function resourceCanPreviewVideo(part: Record<string, unknown>) {
  const payload = resourcePayload(part)
  const ext = resourceExtension(payload.uri)
  if (payload.kind === 'video') return true
  if (payload.mime.startsWith('video/')) return true
  return ['mp4', 'mov', 'mkv', 'webm', 'avi', 'flv'].includes(ext)
}

function resourceCanPreviewAudio(part: Record<string, unknown>) {
  const payload = resourcePayload(part)
  const ext = resourceExtension(payload.uri)
  if (payload.kind === 'audio') return true
  if (payload.mime.startsWith('audio/')) return true
  return ['mp3', 'wav', 'ogg', 'flac', 'm4a'].includes(ext)
}
</script>

<template>
  <div class="feed-resource">
    <div class="feed-resource-head">
      <span class="feed-resource-kind">{{ resourceLabel(part) }}</span>
      <span v-if="resourceDisplayName(part)" class="feed-resource-name">{{ resourceDisplayName(part) }}</span>
    </div>
    <img
      v-if="resourceCanPreviewImage(part) && resourcePreviewHref(part)"
      class="feed-resource-image"
      :src="resourcePreviewHref(part)"
      :alt="resourceDisplayName(part) || resourceLabel(part)"
      loading="lazy"
    />
    <video
      v-else-if="resourceCanPreviewVideo(part) && resourcePreviewHref(part)"
      class="feed-resource-video"
      controls
      preload="metadata"
      :src="resourcePreviewHref(part)"
    ></video>
    <audio
      v-else-if="resourceCanPreviewAudio(part) && resourcePreviewHref(part)"
      class="feed-resource-audio"
      controls
      preload="metadata"
      :src="resourcePreviewHref(part)"
    ></audio>
    <div class="feed-resource-actions">
      <a
        v-if="resourcePreviewHref(part)"
        class="feed-resource-link"
        :href="resourcePreviewHref(part)"
        target="_blank"
        rel="noreferrer"
      >Open</a>
      <a
        v-if="resourceDownloadHref(part)"
        class="feed-resource-link"
        :href="resourceDownloadHref(part)"
        target="_blank"
        rel="noreferrer"
      >Download</a>
    </div>
    <div class="feed-resource-uri">{{ resourcePayload(part).uri }}</div>
  </div>
</template>

<style scoped>
.feed-resource {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-radius: 8px;
  padding: 8px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(2, 6, 23, 0.35);
}

.feed-resource-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.feed-resource-kind {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  color: rgba(148, 163, 184, 0.9);
}

.feed-resource-name {
  font-size: 12px;
  color: rgba(226, 232, 240, 0.95);
  word-break: break-word;
}

.feed-resource-image {
  width: 100%;
  max-width: 380px;
  max-height: 280px;
  object-fit: contain;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: rgba(0, 0, 0, 0.2);
}

.feed-resource-video {
  width: 100%;
  max-width: 420px;
  max-height: 300px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: #000;
}

.feed-resource-audio {
  width: 100%;
  max-width: 420px;
}

.feed-resource-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.feed-resource-link {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(56, 189, 248, 0.45);
  background: rgba(14, 116, 144, 0.2);
  color: rgba(186, 230, 253, 0.98);
  text-decoration: none;
  font-size: 11px;
}

.feed-resource-uri {
  font-size: 12px;
  color: rgba(148, 163, 184, 0.92);
  word-break: break-all;
}
</style>
