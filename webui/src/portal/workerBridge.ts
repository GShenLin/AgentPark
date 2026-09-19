import { decodeBase64, encodeBase64 } from './crypto'
import type { BrowserPeerRpc } from './rpc'

export async function attachBoardWorker(rpc: BrowserPeerRpc): Promise<() => void> {
  if (!navigator.serviceWorker) throw new Error('This browser does not support the cloud Board transport.')
  const listener = (event: MessageEvent) => {
    if (event.data?.kind !== 'portal-http' || !event.ports[0]) return
    const port = event.ports[0]
    const data = event.data
    void rpc.http({ method: data.method, path: data.path, headers: data.headers,
      body: encodeBase64(new Uint8Array(data.body)) }).then(reply => {
        const body = decodeBase64(reply.body).buffer
        port.postMessage({ status: reply.status, headers: reply.headers, body }, [body])
      }).catch(error => port.postMessage({ error: String(error) })).finally(() => port.close())
  }
  navigator.serviceWorker.addEventListener('message', listener)
  try {
    await navigator.serviceWorker.register('/portal-sw.js', { scope: '/' })
    await navigator.serviceWorker.ready
    if (!navigator.serviceWorker.controller) {
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('Board request routing could not be initialized. Reload this page.')), 10000)
        navigator.serviceWorker.addEventListener('controllerchange', () => { clearTimeout(timer); resolve() }, { once: true })
      })
    }
  } catch (error) { navigator.serviceWorker.removeEventListener('message', listener); throw error }
  return () => navigator.serviceWorker.removeEventListener('message', listener)
}
