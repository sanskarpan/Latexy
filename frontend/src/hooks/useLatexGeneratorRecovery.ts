'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

const GENERATION_LEAVES = ['d14_latex', 'd14_table_text', 'd14_table_image', 'd14_math_text', 'd14_math_image'] as const

interface GeneratorRecoveryOptions {
  ownerId: string | null
  documentId: string
  authReady: boolean
  can: (feature: string) => boolean
  newWorkAllowed: boolean
  sourceLoadReady: () => boolean
  active: boolean
}

/** Preserve a visited generator without turning recovery into new admission.
 * The owner comes from useRequireAuth's last-known identity, so a failed or
 * pending refresh does not erase local work. Only confirmed scope changes reset
 * it. Object identity and the mount key both fence document/account A → B → A.
 */
export function useLatexGeneratorRecovery(options: GeneratorRecoveryOptions) {
  const scope = useRef({ ownerId: options.ownerId, documentId: options.documentId, epoch: 0, visited: false, recovery: false, alive: true })
  if (scope.current.ownerId !== options.ownerId || scope.current.documentId !== options.documentId) {
    scope.current = { ownerId: options.ownerId, documentId: options.documentId, epoch: scope.current.epoch + 1, visited: false, recovery: false, alive: true }
  }
  const identity = scope.current
  const current = useRef(options)
  current.current = options
  const [, refresh] = useState(0)
  useEffect(() => {
    identity.alive = true
    return () => { identity.alive = false }
  }, [identity])
  const available = Boolean(identity.ownerId && identity.recovery)
  const canStart = Boolean(options.ownerId && options.authReady && options.newWorkAllowed
    && options.sourceLoadReady()
    && options.can('d14') && options.can('ai_writing') && GENERATION_LEAVES.some(leaf => options.can(leaf)))
  const canAccess = available || canStart
  if (options.active && canAccess) identity.visited = true

  const onRecoveryChange = useCallback((next: boolean) => {
    if (scope.current !== identity || !identity.alive || !identity.ownerId || identity.recovery === next) return
    identity.recovery = next
    refresh(value => value + 1)
  }, [identity])

  const mayInsert = useCallback(() => scope.current === identity && identity.alive && Boolean(identity.ownerId)
    && current.current.active && current.current.authReady && current.current.newWorkAllowed
    && current.current.sourceLoadReady() && current.current.can('c01'), [identity])

  const mayStart = useCallback(() => {
    const input = current.current
    return scope.current === identity && identity.alive && Boolean(identity.ownerId) && input.active
      && input.authReady && input.newWorkAllowed && input.sourceLoadReady()
      && input.can('d14') && input.can('ai_writing') && GENERATION_LEAVES.some(leaf => input.can(leaf))
  }, [identity])

  return {
    key: `latex-generator:${identity.epoch}`,
    mounted: Boolean(identity.ownerId && identity.visited),
    available,
    canStart,
    canAccess,
    onRecoveryChange,
    mayInsert,
    mayStart,
  }
}

export type LatexGeneratorRecovery = ReturnType<typeof useLatexGeneratorRecovery>

type SourceLoadStatus = 'unresolved' | 'loading' | 'ready' | 'error' | 'pdf-only'
type SourceKind = 'server' | 'offline'

/** Authoritative source ownership is independent of a mounted recovery panel.
 * Refreshes invalidate admission immediately; only the current load can renew
 * it. A remembered PDF never authorizes using an unresolved editable source.
 */
export function useEditorSourceLoadScope(ownerId: string | null, documentId: string, sessionReference: unknown, authReady: boolean) {
  const scope = useRef({ ownerId, documentId, sessionReference, authReady, epoch: 0, sequence: 0,
    status: 'unresolved' as SourceLoadStatus, kind: null as SourceKind | null, alive: true })
  // Authentication refresh is an admission boundary, not a recovery boundary.
  // Renew synchronously, before passive fetch cleanup/setup can run, using the
  // stable session store reference and primitive readiness value.
  if (scope.current.ownerId !== ownerId || scope.current.documentId !== documentId
    || scope.current.sessionReference !== sessionReference || scope.current.authReady !== authReady) {
    scope.current = { ownerId, documentId, sessionReference, authReady, epoch: scope.current.epoch + 1, sequence: 0,
      status: 'unresolved', kind: null, alive: true }
  }
  const identity = scope.current
  const [, refresh] = useState(0)
  useEffect(() => {
    identity.alive = true
    return () => { identity.alive = false }
  }, [identity])
  type Ticket = { identity: typeof identity; sequence: number }
  const beginLoad = useCallback((): Ticket => {
    identity.sequence += 1
    identity.status = 'loading'
    identity.kind = null
    refresh(value => value + 1)
    return { identity, sequence: identity.sequence }
  }, [identity])
  const ownsLoad = useCallback((ticket: Ticket) => scope.current === ticket.identity && ticket.identity.alive
    && ticket.sequence === ticket.identity.sequence, [])
  const finishLoad = useCallback((ticket: Ticket, status: SourceLoadStatus, kind: SourceKind | null = null) => {
    if (!ownsLoad(ticket)) return false
    ticket.identity.status = status
    ticket.identity.kind = kind
    refresh(value => value + 1)
    return true
  }, [ownsLoad])
  const isSourceReady = useCallback(() => scope.current === identity && identity.alive && identity.status === 'ready', [identity])
  return { status: identity.status, kind: identity.kind, epoch: identity.epoch, beginLoad, finishLoad, ownsLoad, isSourceReady }
}

/** The real page's load boundary keeps a visited same-scope editor subtree at
 * the same position. Initial/new-scope loads still use the blocking load view.
 */
export function editorRecoveryLoadBoundary({ preserveRecovery, sourceStatus, isLoading, resumeLoadError, hasSession, sessionError, offlineDraftLoaded, offlinePdfLoaded }: {
  preserveRecovery: boolean
  sourceStatus: SourceLoadStatus
  isLoading: boolean
  resumeLoadError: string | null
  hasSession: boolean
  sessionError: unknown
  offlineDraftLoaded: boolean
  offlinePdfLoaded: boolean
}): 'editor' | 'loading' | 'error' | 'session-error' | 'empty' {
  if (preserveRecovery) return 'editor'
  if (isLoading || sourceStatus === 'unresolved' || sourceStatus === 'loading') return 'loading'
  if (resumeLoadError) return 'error'
  if (sessionError && !hasSession && !offlineDraftLoaded && !offlinePdfLoaded) return 'session-error'
  if (!hasSession && !offlineDraftLoaded && !offlinePdfLoaded) return 'empty'
  if (sourceStatus === 'error') return 'error'
  return 'editor'
}
