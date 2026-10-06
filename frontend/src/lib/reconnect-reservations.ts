import type { OfflineDraft } from '@/lib/offline-drafts'
import type { QueuedCompile } from '@/lib/compile-queue'

/**
 * Process-local reservations for reconnect work.
 *
 * These are deliberately transient: they prevent duplicate HTTP submissions
 * from overlapping reconnect effects in this browser context, but do not act
 * as a durable claim, cross-tab lock, or retry suppressor.
 */
const activeReservations = new Set<string>()

export type ReconnectReservation = () => void

export function acquireReconnectReservation(key: string): ReconnectReservation | null {
  if (activeReservations.has(key)) return null
  activeReservations.add(key)
  let released = false
  return () => {
    if (released) return
    released = true
    activeReservations.delete(key)
  }
}

export function draftReconnectReservationKey(draft: OfflineDraft): string {
  // savedAt is the local revision marker. Include the content fields as well
  // so two revisions created in the same millisecond cannot share a claim.
  return JSON.stringify([
    'draft',
    draft.ownerId,
    draft.resumeId,
    draft.title,
    draft.latexContent,
    draft.expectedLatexContent ?? null,
    draft.savedAt.getTime(),
    draft.syncStatus,
  ])
}

export function compileReconnectReservationKey(ownerId: string, job: QueuedCompile): string {
  return JSON.stringify(['compile', ownerId, job.id])
}
