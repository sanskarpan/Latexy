'use client'

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useSession } from '@/lib/auth-client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEntitlements } from '@/contexts/EntitlementsContext'
import { capabilityForRoute } from '@/lib/capability-ui-policy'
import CapabilityGate from '@/components/CapabilityGate'
import { CapabilityRecoveryContext, type CapabilityDraftRecovery } from '@/contexts/CapabilityRecoveryContext'
import { downloadBlob } from '@/lib/download'

/** Generation and optional editing modes only. Owned data, recovery, settings,
 * sharing revocation and billing management routes are deliberately reachable.
 */
export default function CapabilityRouteBoundary({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const { data: session } = useSession()
  const { can, loading } = useEntitlements()
  const identity = session?.user?.id ?? 'anonymous'
  const [recovery, setRecovery] = useState<CapabilityDraftRecovery | null>(null)
  const retained = useRef<{ identity: string; pathname: string } | null>(null)
  const feature = capabilityForRoute(pathname)
  const allowed = !feature || can(feature)
  if (retained.current?.identity !== identity || retained.current?.pathname !== pathname) retained.current = null
  if (allowed) retained.current = { identity, pathname }
  const ownedRecovery = recovery?.ownerId === identity && recovery.pathname === pathname ? recovery : null
  useEffect(() => {
    if (allowed || !ownedRecovery?.dirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [allowed, ownedRecovery?.dirty])
  if (!feature) return <>{children}</>
  const confirmLeave = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (ownedRecovery?.dirty && !window.confirm('This page contains unsaved builder fields. Download the current draft before leaving. Leave anyway?')) event.preventDefault()
  }
  const builderResumeId = /^\/workspace\/builder\/([^/]+)$/.exec(pathname)?.[1]
  return (
    <CapabilityRecoveryContext.Provider value={setRecovery}>
      {/* Keep an already-open draft mounted during refresh/revocation. Inert +
          hidden removes every interaction while retaining unsaved local input.
          A different identity never receives the retained subtree. */}
      {retained.current && <div hidden={!allowed} ref={(node) => { if (node) node.inert = !allowed }}>{children}</div>}
      {!allowed && <div className="mx-auto max-w-xl space-y-4 px-4 py-12">
        <h1 className="text-2xl font-semibold text-fg">{loading ? 'Checking feature availability' : 'Feature unavailable'}</h1>
        <CapabilityGate feature={feature} fallback>{null}</CapabilityGate>
        {ownedRecovery && <div className="space-y-2 rounded-lg border border-warn/30 bg-warn/10 p-4 text-sm text-fg-2">
          <p>{ownedRecovery.dirty ? 'Your unsaved builder fields are still held in this page.' : 'Your current builder fields are still held in this page.'} Download them before navigating away. The source editor contains the last saved version.</p>
          <button type="button" className="font-semibold text-accent-strong underline" onClick={() => downloadBlob(new Blob([ownedRecovery.read()], { type: 'application/json' }), ownedRecovery.filename)}>Download current builder draft (.json)</button>
        </div>}
        <p className="text-sm text-fg-3">Your saved documents and source editor remain available.</p>
        <div className="flex gap-4 text-sm text-accent-strong">
          {builderResumeId && builderResumeId !== 'new' && <Link onClick={confirmLeave} href={`/workspace/${encodeURIComponent(builderResumeId)}/edit`}>Open source editor</Link>}
          <Link onClick={confirmLeave} href="/workspace">Back to workspace</Link>
        </div>
      </div>}
    </CapabilityRecoveryContext.Provider>
  )
}
