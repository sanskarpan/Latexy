'use client'

import { createContext, useContext, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'

export interface CapabilityDraftRecovery {
  ownerId: string
  pathname: string
  filename: string
  dirty: boolean
  read: () => string
}
export const CapabilityRecoveryContext = createContext<(draft: CapabilityDraftRecovery | null) => void>(() => {})

/** Only explicit application draft state is registered, never DOM/form scraping. */
export function useCapabilityDraftRecovery(ownerId: string, filename: string, dirty: boolean, draft: unknown) {
  const pathname = usePathname()
  const register = useContext(CapabilityRecoveryContext)
  const draftRef = useRef(draft)
  draftRef.current = draft
  useEffect(() => {
    register({ ownerId, pathname, filename, dirty, read: () => JSON.stringify(draftRef.current, null, 2) })
    return () => register(null)
  }, [register, ownerId, pathname, filename, dirty])
}
