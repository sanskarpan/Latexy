'use client'

import { createContext, useContext } from 'react'

/** Render-current authority for retained private-content callbacks. */
export type AccountContentScope = {
  /** Stable through same-owner uncertainty; never reused after account/route ABA. */
  readonly recoveryIdentity: object
  isCurrent: () => boolean
  /** Current snapshot ownership, including a still-unready cold/offline load. */
  isAdmissionCurrent: () => boolean
  /** Pinned to this render's admission lease; an old lease never revives. */
  canAdmit: () => boolean
}
const AccountContentScopeContext = createContext<AccountContentScope | null>(null)
export const AccountContentScopeProvider = AccountContentScopeContext.Provider
export function useAccountContentScope(): AccountContentScope | null {
  return useContext(AccountContentScopeContext)
}
