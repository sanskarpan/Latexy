'use client'

import { createContext, useCallback, useContext, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { downloadBlob } from '@/lib/download'

export interface CapabilityDraftRecovery {
  ownerId: string
  pathname: string
  filename: string
  dirty: boolean
  read: () => string | null
}
export const CapabilityRecoveryContext = createContext<(draft: CapabilityDraftRecovery | null) => void>(() => {})

/** A revoked callback must not serialize another owner/document incarnation. */
export function downloadCapabilityDraft(draft: CapabilityDraftRecovery) {
  const content = draft.read()
  if (content !== null) downloadBlob(new Blob([content], { type: 'application/json' }), draft.filename)
}

/** Only explicit application draft state is registered, never DOM/form scraping. */
export function useCapabilityDraftRecovery(ownerId: string, filename: string, dirty: boolean, draft: unknown, enabled = true) {
  const pathname = usePathname()
  const register = useContext(CapabilityRecoveryContext)
  const draftRef = useRef(draft)
  draftRef.current = draft
  const scopeRef = useRef({ ownerId, pathname, active: true, enabled })
  if (scopeRef.current.ownerId !== ownerId || scopeRef.current.pathname !== pathname) {
    scopeRef.current = { ownerId, pathname, active: true, enabled }
  }
  const scope = scopeRef.current
  scope.enabled = enabled
  const read = useCallback(() => scopeRef.current === scope && scope.active && scope.enabled ? JSON.stringify(draftRef.current, null, 2) : null, [scope])
  useEffect(() => {
    scope.active = true
    register(enabled ? { ownerId, pathname, filename, dirty, read } : null)
    return () => { scope.active = false; register(null) }
  }, [register, ownerId, pathname, filename, dirty, enabled, scope, read])
  return () => downloadCapabilityDraft({ ownerId, pathname, filename, dirty, read })
}
