'use client'

import { useEntitlements } from '@/contexts/EntitlementsContext'

/** Keep core documents usable while making failed optional-tool checks explicit. */
export default function CapabilityStatusNotice() {
  const { error, refresh } = useEntitlements()
  if (!error) return null
  return (
    <div role="alert" className="flex flex-wrap items-center justify-center gap-3 border-b border-warn/30 bg-warn/10 px-4 py-2 text-xs text-fg-2">
      <span>Optional tools are unavailable while feature access is checked. Your saved documents and source editor remain available.</span>
      <button type="button" onClick={refresh} className="font-semibold text-accent-strong underline">Retry feature access</button>
    </div>
  )
}
