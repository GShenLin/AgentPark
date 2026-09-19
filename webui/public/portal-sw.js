/* Routes only requests issued by a cloud Board document to that document's P2P session. */
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()))
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()))

function peerRequest(client, request, cursor) {
  return new Promise((resolve, reject) => {
    const channel = new MessageChannel()
    const timeout = setTimeout(() => { channel.port1.close(); reject(new Error('Board transport timed out.')) }, 60000)
    channel.port1.onmessage = event => {
      clearTimeout(timeout); channel.port1.close()
      if (event.data.error) reject(new Error(event.data.error))
      else resolve(event.data)
    }
    request.clone().arrayBuffer().then(body => {
      if (body.byteLength > 4 * 1024 * 1024) throw new Error('Board request exceeds 4 MiB.')
      const url = new URL(request.url)
      const headers = {}
      for (const key of ['content-type', 'range', 'last-event-id']) if (request.headers.has(key)) headers[key] = request.headers.get(key)
      if (cursor !== undefined) headers['last-event-id'] = cursor
      client.postMessage({ kind: 'portal-http', method: request.method, path: url.pathname + url.search, headers, body }, [channel.port2, body])
    }).catch(error => { clearTimeout(timeout); channel.port1.close(); reject(error) })
  })
}

async function boardFetch(event) {
  const client = await self.clients.get(event.clientId)
  if (!client || !/^\/board\/[a-f0-9]{64}$/.test(new URL(client.url).pathname)) return fetch(event.request)
  const url = new URL(event.request.url)
  if (url.pathname === '/api/app/events/stream') {
    let stopped = false
    let cursor = event.request.headers.get('last-event-id') || undefined
    const stream = new ReadableStream({
      async pull(controller) {
        if (stopped) return
        try {
          const reply = await peerRequest(client, event.request, cursor)
          if (stopped) return
          if (reply.status !== 200) throw new Error('Board event stream rejected the request.')
          cursor = reply.headers['x-peer-event-cursor']
          if (typeof cursor !== 'string') throw new Error('Board event cursor is missing.')
          controller.enqueue(new Uint8Array(reply.body))
        } catch (error) { if (!stopped) { stopped = true; controller.error(error) } }
      },
      cancel() { stopped = true },
    })
    return new Response(stream, { headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' } })
  }
  try {
    const reply = await peerRequest(client, event.request)
    const headers = new Headers(reply.headers)
    headers.set('Cache-Control', 'no-store')
    return new Response([204, 205, 304].includes(reply.status) ? null : reply.body, { status: reply.status, headers })
  } catch (error) {
    return new Response(JSON.stringify({ detail: String(error) }), { status: 502, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } })
  }
}

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url)
  if (url.origin !== self.location.origin || (!url.pathname.startsWith('/api/') && !url.pathname.startsWith('/memories/'))) return
  event.respondWith(boardFetch(event))
})
