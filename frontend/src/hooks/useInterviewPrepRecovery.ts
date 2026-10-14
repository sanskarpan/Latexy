'use client'

import { useCallback, useRef } from 'react'
import type { InterviewPrepScope } from '@/components/InterviewPrepPanel'
import { useAccountContentScope } from '@/contexts/AccountContentScope'

/** Interview recovery follows the account/document incarnation, while new work
 * requires the current admission lease and the editor's committed source. */
export function useInterviewPrepRecovery({ ownerId, resumeId, authToken, authReady, sourceReady, can }: {
  ownerId: string | null
  resumeId: string
  authToken: string | null
  authReady: boolean
  sourceReady: () => boolean
  can: (feature: string) => boolean
}) {
  const account = useAccountContentScope()
  const recoveryIdentity = account?.recoveryIdentity ?? null
  const scopeRef = useRef<InterviewPrepScope>({ ownerId, resumeId, authToken, generation: 0, recoveryIdentity,
    ready: false, authReady: false, recoveryAvailable: false })
  if (scopeRef.current.ownerId !== ownerId || scopeRef.current.resumeId !== resumeId
    || scopeRef.current.recoveryIdentity !== recoveryIdentity) {
    scopeRef.current = { ownerId, resumeId, authToken, generation: scopeRef.current.generation + 1, recoveryIdentity,
      ready: false, authReady: false, recoveryAvailable: false }
  }
  const scope = scopeRef.current
  scope.authToken = authToken
  scope.authReady = Boolean(account?.canAdmit() && ownerId && authReady)
  scope.ready = scope.authReady && sourceReady()
  const grants = useRef(can)
  grants.current = can
  const isCurrent = Boolean(account?.isCurrent() && ownerId)
  const canAccess = isCurrent && (scope.recoveryAvailable || (scope.ready && (can('e02') || can('e03'))))
  const activate = useCallback(() => {
    if (!account?.isCurrent() || scopeRef.current !== scope || !scope.ownerId) return false
    if (!scope.recoveryAvailable && (!account.canAdmit() || !scope.authReady || !sourceReady()
      || (!grants.current('e02') && !grants.current('e03')))) return false
    scope.recoveryAvailable = true
    return true
  }, [account, scope, sourceReady])
  return { scopeRef, canAccess, mounted: isCurrent && scope.recoveryAvailable, activate }
}
