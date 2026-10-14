'use client'

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useAccountContentScope } from '@/contexts/AccountContentScope'

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
  const accountScope = useAccountContentScope()
  const recoveryIdentity = accountScope?.recoveryIdentity
  const scope = useRef({ ownerId: options.ownerId, documentId: options.documentId, recoveryIdentity, epoch: 0, visited: false, recovery: false, alive: true })
  if (scope.current.ownerId !== options.ownerId || scope.current.documentId !== options.documentId || scope.current.recoveryIdentity !== recoveryIdentity) {
    scope.current = { ownerId: options.ownerId, documentId: options.documentId, recoveryIdentity, epoch: scope.current.epoch + 1, visited: false, recovery: false, alive: true }
  }
  const identity = scope.current
  const current = useRef(options)
  current.current = options
  const [, refresh] = useState(0)
  useEffect(() => {
    identity.alive = true
    return () => { identity.alive = false }
  }, [identity])
  const available = Boolean(accountScope?.isCurrent() && identity.ownerId && identity.recovery)
  const canStart = Boolean(accountScope?.canAdmit() && options.ownerId && options.authReady && options.newWorkAllowed
    && options.sourceLoadReady()
    && options.can('d14') && options.can('ai_writing') && GENERATION_LEAVES.some(leaf => options.can(leaf)))
  const canAccess = available || canStart
  if (options.active && canAccess) identity.visited = true

  const onRecoveryChange = useCallback((next: boolean) => {
    if (!(accountScope?.isCurrent() ?? false) || scope.current !== identity || !identity.alive || !identity.ownerId || identity.recovery === next) return
    identity.recovery = next
    refresh(value => value + 1)
  }, [accountScope, identity])

  const mayInsert = useCallback(() => Boolean(accountScope?.canAdmit()) && scope.current === identity && identity.alive && Boolean(identity.ownerId)
    && current.current.active && current.current.authReady && current.current.newWorkAllowed
    && current.current.sourceLoadReady() && current.current.can('c01'), [accountScope, identity])

  const mayStart = useCallback(() => {
    const input = current.current
    return Boolean(accountScope?.canAdmit()) && scope.current === identity && identity.alive && Boolean(identity.ownerId) && input.active
      && input.authReady && input.newWorkAllowed && input.sourceLoadReady()
      && input.can('d14') && input.can('ai_writing') && GENERATION_LEAVES.some(leaf => input.can(leaf))
  }, [accountScope, identity])

  return {
    key: `latex-generator:${identity.epoch}`,
    mounted: Boolean(accountScope?.isCurrent() && identity.ownerId && identity.visited),
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
  const accountScope = useAccountContentScope()
  const scope = useRef({ ownerId, documentId, sessionReference, authReady, accountScope, epoch: 0, sequence: 0, version: 0,
    status: 'unresolved' as SourceLoadStatus, kind: null as SourceKind | null, alive: true })
  // Authentication refresh is an admission boundary, not a recovery boundary.
  // Renew synchronously, before passive fetch cleanup/setup can run, using the
  // stable session store reference and primitive readiness value.
  if (scope.current.ownerId !== ownerId || scope.current.documentId !== documentId
    || scope.current.sessionReference !== sessionReference || scope.current.authReady !== authReady || scope.current.accountScope !== accountScope) {
    scope.current = { ownerId, documentId, sessionReference, authReady, accountScope, epoch: scope.current.epoch + 1, sequence: 0, version: 0,
      status: 'unresolved', kind: null, alive: true }
  }
  const identity = scope.current
  type Snapshot = { identity: typeof identity; sequence: number; version: number; status: SourceLoadStatus; kind: SourceKind | null }
  const [snapshot, publish] = useState<Snapshot>(() => ({ identity, sequence: 0, version: 0, status: 'unresolved', kind: null }))
  const committedReady = useRef<Snapshot | null>(null)
  const [, notifyCommit] = useState(0)
  useEffect(() => {
    identity.alive = true
    return () => { identity.alive = false }
  }, [identity])
  // A mutable completion is only a queued candidate. Its exact React state lane
  // must commit before retained callbacks may use the newly loaded source.
  useLayoutEffect(() => {
    if (snapshot.identity !== identity || snapshot.version !== identity.version || snapshot.status !== 'ready') return
    if (committedReady.current === snapshot) return
    committedReady.current = snapshot
    notifyCommit(value => value + 1)
    return () => { if (committedReady.current === snapshot) committedReady.current = null }
  }, [identity, snapshot])
  type Ticket = { identity: typeof identity; sequence: number }
  const beginLoad = useCallback((): Ticket => {
    if (!(accountScope?.isAdmissionCurrent() ?? false) || scope.current !== identity || !identity.alive) return { identity, sequence: -1 }
    identity.sequence += 1
    identity.status = 'loading'
    identity.kind = null
    identity.version += 1
    publish({ identity, sequence: identity.sequence, version: identity.version, status: 'loading', kind: null })
    return { identity, sequence: identity.sequence }
  }, [accountScope, identity])
  const ownsLoad = useCallback((ticket: Ticket) => Boolean(accountScope?.isAdmissionCurrent()) && scope.current === ticket.identity && ticket.identity.alive
    && (!ticket.identity.authReady || Boolean(accountScope?.canAdmit()))
    && ticket.sequence === ticket.identity.sequence, [accountScope])
  const finishLoad = useCallback((ticket: Ticket, status: SourceLoadStatus, kind: SourceKind | null = null) => {
    if (!ownsLoad(ticket)) return false
    ticket.identity.status = status
    ticket.identity.kind = kind
    ticket.identity.version += 1
    publish({ identity: ticket.identity, sequence: ticket.sequence, version: ticket.identity.version, status, kind })
    return true
  }, [ownsLoad])
  const isSourceReady = useCallback(() => {
    const ready = committedReady.current
    return Boolean(accountScope?.canAdmit()) && scope.current === identity && identity.alive && identity.authReady
      && identity.status === 'ready' && ready?.identity === identity && ready.sequence === identity.sequence
      && ready.version === identity.version && ready.status === 'ready'
  }, [accountScope, identity])
  const currentSnapshot = snapshot.identity === identity && snapshot.version === identity.version ? snapshot : null
  return { status: currentSnapshot?.status ?? (identity.sequence ? 'loading' : 'unresolved'), kind: currentSnapshot?.kind ?? null,
    epoch: identity.epoch, beginLoad, finishLoad, ownsLoad, isSourceReady }
}

/** The real page's load boundary keeps a visited same-scope editor subtree at
 * the same position. Initial/new-scope loads still use the blocking load view.
 */
export function editorRecoveryLoadBoundary({ preserveRecovery, sourceStatus, isLoading, resumeLoadError, hasSession, sessionError, offlineDraftLoaded, offlinePdfLoaded, confirmedSessionEnded = false }: {
  preserveRecovery: boolean
  sourceStatus: SourceLoadStatus
  isLoading: boolean
  resumeLoadError: string | null
  hasSession: boolean
  sessionError: unknown
  offlineDraftLoaded: boolean
  offlinePdfLoaded: boolean
  confirmedSessionEnded?: boolean
}): 'editor' | 'loading' | 'error' | 'session-error' | 'empty' {
  if (confirmedSessionEnded) return 'empty'
  if (preserveRecovery) return 'editor'
  if (isLoading || sourceStatus === 'unresolved' || sourceStatus === 'loading') return 'loading'
  if (resumeLoadError) return 'error'
  if (sessionError && !hasSession && !offlineDraftLoaded && !offlinePdfLoaded) return 'session-error'
  if (!hasSession && !offlineDraftLoaded && !offlinePdfLoaded) return 'empty'
  if (sourceStatus === 'error') return 'error'
  return 'editor'
}
