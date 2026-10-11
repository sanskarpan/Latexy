'use client'

import Link from 'next/link'
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { apiClient } from '@/lib/api-client'
import { supportsGuidedBuilder } from '@/lib/builder-capabilities'

const UNAVAILABLE = 'Guided editing and exports need a compatible server. Retry after the server is updated.'

type BuilderCapability = {
  available: boolean
  ensureCompatible: () => Promise<void>
  isCompatible: () => boolean
}
const CapabilityContext = createContext<BuilderCapability | null>(null)

export function useBuilderCapability() {
  const capability = useContext(CapabilityContext)
  if (!capability) throw new Error('Guided builder requires a capability gate')
  return capability
}

/** Fail closed before mounting a draft, and recheck before every server action. */
export default function BuilderCapabilityGate({ children, resumeId }: { children: ReactNode; resumeId?: string }) {
  const [status, setStatus] = useState<'checking' | 'supported' | 'unavailable'>('checking')
  const [hasOpened, setHasOpened] = useState(false)
  const supportedRef = useRef(false)
  const mountedRef = useRef(false)
  const flightRef = useRef<Promise<void> | null>(null)

  const ensureCompatible = useCallback(async () => {
    if (flightRef.current) return flightRef.current
    const check = async () => {
      try {
        const capabilities = await apiClient.getBuilderCapabilities()
        if (!mountedRef.current) throw new Error('The builder page changed. Please retry.')
        if (!supportsGuidedBuilder(capabilities)) throw new Error(UNAVAILABLE)
        supportedRef.current = true
        setHasOpened(true)
        setStatus('supported')
      } catch (error) {
        supportedRef.current = false
        if (mountedRef.current) setStatus('unavailable')
        throw error
      }
    }
    const flight = check()
    flightRef.current = flight
    try { await flight } finally { if (flightRef.current === flight) flightRef.current = null }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    void ensureCompatible().catch(() => {})
    return () => {
      mountedRef.current = false
      supportedRef.current = false
    }
  }, [ensureCompatible])

  const isCompatible = useCallback(() => mountedRef.current && supportedRef.current, [])
  const capability = useMemo(() => ({ ensureCompatible, isCompatible, available: status === 'supported' }), [ensureCompatible, isCompatible, status])
  const confirmLeaving = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (hasOpened && !window.confirm('Any unsaved guided edits will be left behind. Continue?')) event.preventDefault()
  }

  return (
    <CapabilityContext.Provider value={capability}>
      {status !== 'supported' && <section className="content-shell py-16">
        {status === 'checking' ? <p role="status" className="text-sm text-fg-2">Checking guided builder compatibility…</p> : <div role="alert" className="mx-auto max-w-lg rounded-[var(--radius-lg)] border border-warn/30 bg-warn/10 p-6">
          <h1 className="text-lg font-semibold text-fg">Guided builder is unavailable</h1>
          <p className="mt-2 text-sm text-fg-2">The server does not yet support this version of the guided builder, or its status could not be checked. Guided edits and exports are paused.</p>
          {hasOpened && <p className="mt-2 text-sm text-fg-2">Your unsaved edits are still in this tab while you retry.</p>}
          <button type="button" onClick={() => {
            setStatus('checking')
            void ensureCompatible().catch(() => {})
          }} className="mt-4 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-medium text-accent-fg">Retry compatibility check</button>
        </div>}
        <nav aria-label="Other resume options" className="mt-5 flex flex-wrap justify-center gap-4 text-sm text-fg">
          <Link href="/workspace" onClick={confirmLeaving}>Back to workspace</Link>
          <Link href={resumeId ? `/workspace/${resumeId}/edit` : '/workspace/new'} onClick={confirmLeaving}>{resumeId ? 'Open Advanced Editor' : 'Use source editor'}</Link>
        </nav>
      </section>}
      {/* Keep an existing draft alive after a failed action check, but expose no
          unsupported fields or export controls until a fresh check succeeds. */}
      <div hidden={status !== 'supported'}>
        <fieldset disabled={status !== 'supported'} className="min-w-0">
          {hasOpened ? children : null}
        </fieldset>
      </div>
    </CapabilityContext.Provider>
  )
}
