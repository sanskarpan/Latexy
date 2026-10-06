import { describe, expect, it } from 'vitest'
import {
  acquireReconnectReservation,
  compileReconnectReservationKey,
  draftReconnectReservationKey,
} from '@/lib/reconnect-reservations'

const draft = (savedAt: number, latexContent = 'source') => ({
  ownerId: 'owner-a',
  resumeId: 'resume-a',
  title: 'Resume',
  latexContent,
  savedAt: new Date(savedAt),
  syncStatus: 'pending' as const,
})

describe('reconnect transient reservations', () => {
  it('allows only one in-flight reservation for an exact item', () => {
    const key = compileReconnectReservationKey('owner-a', {
      id: 'job-a', ownerId: 'owner-a', resumeId: 'resume-a', latexContent: 'source', queuedAt: new Date(1),
    })
    const release = acquireReconnectReservation(key)
    expect(release).toEqual(expect.any(Function))
    expect(acquireReconnectReservation(key)).toBeNull()
    release?.()
    const reacquired = acquireReconnectReservation(key)
    expect(reacquired).toEqual(expect.any(Function))
    expect(acquireReconnectReservation(key)).toBeNull()
    // Releasing the old token again must not clear this later reservation.
    release?.()
    expect(acquireReconnectReservation(key)).toBeNull()
    reacquired?.()
  })

  it('does not block other owners, queue items, or draft revisions', () => {
    const compileA = compileReconnectReservationKey('owner-a', {
      id: 'job-a', ownerId: 'owner-a', resumeId: 'resume-a', latexContent: 'source', queuedAt: new Date(1),
    })
    const compileB = compileReconnectReservationKey('owner-b', {
      id: 'job-a', ownerId: 'owner-b', resumeId: 'resume-a', latexContent: 'source', queuedAt: new Date(1),
    })
    const draftA = draftReconnectReservationKey(draft(1))
    const draftRevision = draftReconnectReservationKey(draft(2))
    const releases = [compileA, compileB, draftA, draftRevision].map(key => acquireReconnectReservation(key))
    expect(releases.every(Boolean)).toBe(true)
    releases.forEach(release => release?.())
  })

  it('releases in finally so a failed request can retry', () => {
    const key = draftReconnectReservationKey(draft(3))
    const release = acquireReconnectReservation(key)
    try {
      throw new Error('simulated HTTP failure')
    } catch {
      // Reconnect callers release in their finally block after failures.
    } finally {
      release?.()
    }
    const reacquired = acquireReconnectReservation(key)
    expect(reacquired).toEqual(expect.any(Function))
    reacquired?.()
  })
})
