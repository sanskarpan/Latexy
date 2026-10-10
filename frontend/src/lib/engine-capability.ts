export type EngineCapability =
  | { status: 'supported' }
  | { status: 'unsupported' }
  | { status: 'error'; reason: 'authorization' | 'unavailable' }

/** Only this public capability endpoint's 404 means an older deployment.
 * A document's 404 may hide denied access and must never enable a fallback.
 */
export async function readEngineCapability(response: Response): Promise<EngineCapability> {
  if (response.status === 404) return { status: 'unsupported' }
  if (response.status === 401 || response.status === 403) return { status: 'error', reason: 'authorization' }
  if (!response.ok) return { status: 'error', reason: 'unavailable' }
  const body: unknown = await response.json()
  return body && typeof body === 'object' && 'resume_engine_version' in body && body.resume_engine_version === 1
    ? { status: 'supported' } : { status: 'unsupported' }
}

/** Derive a temporary mode without overwriting the user's saved preference. */
export function engineEditorMode<T extends 'pdf' | 'source' | 'wysiwyg'>(preferred: T, status: EngineCapability['status'] | 'loading', sourceFallback = status === 'unsupported'): T | 'source' {
  return preferred === 'pdf' && sourceFallback ? 'source' : preferred
}
