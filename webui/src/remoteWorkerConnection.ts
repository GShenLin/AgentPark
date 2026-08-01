import {
  ApiHttpError,
  discoverLocalRemoteWorker,
  pairRemoteWorker,
  waitForRemoteWorker,
  type RemoteWorker,
} from './api'

const ONLINE_PROBE_SECONDS = 0.5
const RECONNECT_WAIT_SECONDS = 6
const PAIR_ATTEMPTS = 24
const PAIR_RETRY_DELAY_MS = 250

type RemoteWorkerResponse = {
  ok: boolean
  worker: RemoteWorker
}

function isHttpStatus(error: unknown, status: number): error is ApiHttpError {
  return error instanceof ApiHttpError && error.status === status
}

function delay(milliseconds: number) {
  return new Promise(resolve => window.setTimeout(resolve, milliseconds))
}

export async function pairLocalRemoteWorker(): Promise<RemoteWorkerResponse> {
  await discoverLocalRemoteWorker()
  let lastNotFound: ApiHttpError | undefined
  for (let attempt = 0; attempt < PAIR_ATTEMPTS; attempt += 1) {
    try {
      return await pairRemoteWorker()
    } catch (error) {
      if (!isHttpStatus(error, 404)) throw error
      lastNotFound = error
      if (attempt + 1 < PAIR_ATTEMPTS) {
        await delay(PAIR_RETRY_DELAY_MS)
      }
    }
  }
  throw lastNotFound || new Error('Remote worker did not register with AgentPark in time.')
}

export async function ensureBoundRemoteWorkerOnline(workerId: string): Promise<RemoteWorkerResponse> {
  const normalizedWorkerId = String(workerId || '').trim()
  if (!normalizedWorkerId) {
    throw new Error('Remote is enabled, but this node has no bound remote worker.')
  }

  try {
    return await waitForRemoteWorker(normalizedWorkerId, ONLINE_PROBE_SECONDS)
  } catch (error) {
    if (!isHttpStatus(error, 409)) throw error
  }

  try {
    await discoverLocalRemoteWorker()
  } catch (error) {
    throw new Error(
      `Remote worker ${normalizedWorkerId} is offline and its local companion could not be reached: ${
        String((error as { message?: unknown })?.message || error)
      }`,
    )
  }

  try {
    return await waitForRemoteWorker(normalizedWorkerId, RECONNECT_WAIT_SECONDS)
  } catch (error) {
    if (!isHttpStatus(error, 409)) throw error
    throw new Error(
      `Remote worker ${normalizedWorkerId} is offline. Local discovery succeeded, but the bound worker did not reconnect within ${RECONNECT_WAIT_SECONDS}s.`,
    )
  }
}
