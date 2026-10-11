'use client'

import type { ReactNode } from 'react'
import { useEntitlements } from '@/contexts/EntitlementsContext'

/** Children are not mounted when denied, so hidden tools cannot run effects. */
export default function CapabilityGate({ feature, children, fallback = false }: {
  feature: string
  children: ReactNode
  fallback?: boolean
}) {
  const { can, loading, error, refresh } = useEntitlements()
  if (can(feature)) return <>{children}</>
  if (!fallback) return null
  return (
    <div role={error ? 'alert' : 'status'} className="rounded-lg border border-line bg-surface p-4 text-sm text-fg-3">
      <p>{loading ? 'Checking feature availability…' : error ? 'Feature availability could not be verified.' : 'This feature is currently unavailable for your plan.'}</p>
      {error && <button type="button" className="mt-2 text-accent-strong underline" onClick={refresh}>Retry</button>}
    </div>
  )
}
