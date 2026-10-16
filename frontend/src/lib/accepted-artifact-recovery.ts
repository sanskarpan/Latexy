import type { RenderArtifact } from '@/lib/event-types'

export interface AcceptedPreviewRecoveryIdentity {
  ownerId: string
  resumeId: string
  generation: number
  source: string
  contentRevision: number
}

export interface AcceptedPreviewRecoveryResponse {
  artifact: (RenderArtifact & { job_id: string }) | null
  source_sha256: string
  content_revision: number
}

export const ACCEPTED_ARTIFACT_RECOVERY_TIMEOUT_MS = 8_000
export const ACCEPTED_ARTIFACT_RECOVERY_RETRY_MAX_MS = 2_000

export function retryAfterMilliseconds(value: string | null, now = Date.now()): number | null {
  if (!value) return null
  const header = value.trim()
  const seconds = Number(header)
  const requested = /^-?\d+(?:\.\d+)?$/.test(header)
    ? (Number.isFinite(seconds) && seconds >= 0 ? seconds * 1_000 : NaN)
    : Date.parse(header) - now
  return Number.isFinite(requested) && requested >= 0 ? requested : null
}

function withinRecoveryDeadline<T>(
  operation: () => Promise<T>,
  signal: AbortSignal | undefined,
  deadline: number,
  now: () => number,
  onTimeout: () => void,
): Promise<T> {
  const remaining = deadline - now()
  if (signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'))
  if (remaining <= 0) {
    onTimeout()
    return Promise.reject(new DOMException('Accepted artifact lookup timed out', 'TimeoutError'))
  }

  return new Promise<T>((resolve, reject) => {
    let settled = false
    const finish = (callback: () => void) => {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      signal?.removeEventListener('abort', onAbort)
      callback()
    }
    const onAbort = () => finish(() => reject(new DOMException('Aborted', 'AbortError')))
    const timeout = setTimeout(() => {
      onTimeout()
      finish(() => reject(new DOMException('Accepted artifact lookup timed out', 'TimeoutError')))
    }, remaining)
    signal?.addEventListener('abort', onAbort, { once: true })
    // Register the deadline before starting an operation that may itself wait
    // for authentication. Abandon queued work if its caller has already left.
    Promise.resolve().then(() => {
      if (settled || signal?.aborted) throw new DOMException('Aborted', 'AbortError')
      if (now() >= deadline) {
        onTimeout()
        throw new DOMException('Accepted artifact lookup timed out', 'TimeoutError')
      }
      return operation()
    }).then(value => {
      if (now() >= deadline) {
        onTimeout()
        finish(() => reject(new DOMException('Accepted artifact lookup timed out', 'TimeoutError')))
      } else {
        finish(() => resolve(value))
      }
    }, error => finish(() => reject(error)))
  })
}

/**
 * Retry a transient accepted-artifact 503 at most once, within one overall
 * deadline. This endpoint is a read: an unknown result must remain unknown and
 * must never be interpreted as permission to submit a duplicate compile.
 */
export async function fetchAcceptedArtifact<T>(
  request: (signal: AbortSignal) => Promise<Response>,
  parse: (response: Response) => Promise<T>,
  signal?: AbortSignal,
  now: () => number = Date.now,
): Promise<T> {
  const deadline = now() + ACCEPTED_ARTIFACT_RECOVERY_TIMEOUT_MS
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    const remaining = deadline - now()
    if (remaining <= 0) throw new DOMException('Accepted artifact lookup timed out', 'TimeoutError')
    const controller = new AbortController()
    const onAbort = () => controller.abort()
    signal?.addEventListener('abort', onAbort, { once: true })
    let response: Response
    let retryAfter: number | null = null
    try {
      response = await withinRecoveryDeadline(() => request(controller.signal), signal, deadline, now, onAbort)
      if (response.status !== 503 || attempt !== 0) {
        return await withinRecoveryDeadline(() => parse(response), signal, deadline, now, onAbort)
      }

      retryAfter = retryAfterMilliseconds(response.headers.get('Retry-After'), now())
      const remainingAfterResponse = deadline - now()
      if (retryAfter === null || retryAfter > ACCEPTED_ARTIFACT_RECOVERY_RETRY_MAX_MS
          || retryAfter >= remainingAfterResponse) {
        return await withinRecoveryDeadline(() => parse(response), signal, deadline, now, onAbort)
      }
    } finally {
      signal?.removeEventListener('abort', onAbort)
    }
    if (retryAfter === null) return await withinRecoveryDeadline(() => parse(response), signal, deadline, now, onAbort)
    const delay = retryAfter
    let retryTimer: ReturnType<typeof setTimeout> | undefined
    try {
      await withinRecoveryDeadline(() => new Promise<void>(resolve => {
        retryTimer = setTimeout(resolve, delay)
      }), signal, deadline, now, onAbort)
    } finally {
      if (retryTimer !== undefined) clearTimeout(retryTimer)
    }
  }
  throw new DOMException('Accepted artifact lookup timed out', 'TimeoutError')
}

export function isCurrentAcceptedPreviewRecovery(
  expected: AcceptedPreviewRecoveryIdentity,
  current: AcceptedPreviewRecoveryIdentity | null,
): boolean {
  return Boolean(current
    && current.ownerId === expected.ownerId
    && current.resumeId === expected.resumeId
    && current.generation === expected.generation
    && current.source === expected.source
    && current.contentRevision === expected.contentRevision)
}

export async function resolveCurrentAcceptedPreviewRecovery(
  expected: AcceptedPreviewRecoveryIdentity,
  getCurrent: () => AcceptedPreviewRecoveryIdentity | null,
  operation: Promise<AcceptedPreviewRecoveryResponse>,
): Promise<AcceptedPreviewRecoveryResponse | null> {
  const response = await operation
  return isCurrentAcceptedPreviewRecovery(expected, getCurrent()) ? response : null
}

export function isMatchingAcceptedArtifact(
  response: AcceptedPreviewRecoveryResponse,
  identity: AcceptedPreviewRecoveryIdentity,
  sourceSha256: string,
): response is AcceptedPreviewRecoveryResponse & { artifact: RenderArtifact & { job_id: string } } {
  const artifact = response.artifact
  return Boolean(artifact
    && response.content_revision === identity.contentRevision
    && response.source_sha256 === sourceSha256
    && artifact.document_id === identity.resumeId
    && artifact.content_revision === identity.contentRevision
    && artifact.source_sha256 === sourceSha256
    && artifact.branch === 'draft'
    && /^[a-f0-9]{64}$/.test(artifact.artifact_id)
    && /^[A-Za-z0-9_-]{1,255}$/.test(artifact.job_id))
}

export function shouldSubmitInitialPreview(recovery: 'found' | 'none' | 'unavailable'): boolean {
  return recovery === 'none'
}
