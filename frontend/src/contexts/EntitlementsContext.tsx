'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, ReactNode } from 'react'
import { apiClient } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import { isFeatureAllowed, parseEffectiveFeatures } from '@/lib/entitlement-policy'

interface EntitlementsContextValue {
  /** Effective feature map for this exact identity and refresh generation. */
  features: Record<string, boolean>
  loading: boolean
  loaded: boolean
  error: string | null
  /** Unknown, unresolved and failed capabilities are denied; recovery stays available. */
  can: (featureKey: string) => boolean
  refresh: () => void
}

const EMPTY_FEATURES: Record<string, boolean> = Object.freeze({})
const EntitlementsContext = createContext<EntitlementsContextValue>({
  features: EMPTY_FEATURES,
  loading: true,
  loaded: false,
  error: null,
  can: (key) => isFeatureAllowed(EMPTY_FEATURES, key),
  refresh: () => {},
})

type Snapshot = {
  identity: string
  generation: number
  features: Record<string, boolean>
  error: string | null
}

export function EntitlementsProvider({ children }: { children: ReactNode }) {
  const { data: session, isPending, error: sessionError } = useSession()
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [generation, setGeneration] = useState(0)
  const identity = session?.user?.id ? `user:${session.user.id}` : 'anonymous'
  const identityReady = !isPending && !sessionError
  const scopeRef = useRef({ identity, ready: identityReady, epoch: 0 })
  if (scopeRef.current.identity !== identity || scopeRef.current.ready !== identityReady) {
    scopeRef.current = { identity, ready: identityReady, epoch: scopeRef.current.epoch + 1 }
  }
  const scopedIdentity = `${identity}:${scopeRef.current.epoch}`
  const refresh = useCallback(() => setGeneration((n) => n + 1), [])

  useEffect(() => {
    if (!identityReady) return
    let active = true
    // This endpoint uses optional authentication and returns free-plan controls
    // for anonymous visitors too. Never infer availability from sign-in status.
    apiClient.getEntitlements().then((data) => {
      const features = parseEffectiveFeatures(data?.features)
      if (active) setSnapshot({ identity: scopedIdentity, generation, features, error: null })
    }).catch((err: unknown) => {
      if (active) setSnapshot({
        identity: scopedIdentity, generation, features: EMPTY_FEATURES,
        error: err instanceof Error ? err.message : 'Could not load feature availability',
      })
    })
    return () => { active = false }
  }, [scopedIdentity, identityReady, generation])

  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === 'visible') refresh() }
    window.addEventListener('focus', refresh)
    window.addEventListener('latexy:entitlements-updated', refresh)
    document.addEventListener('visibilitychange', onVisible)
    const timer = window.setInterval(onVisible, 30_000)
    return () => {
      window.removeEventListener('focus', refresh)
      window.removeEventListener('latexy:entitlements-updated', refresh)
      document.removeEventListener('visibilitychange', onVisible)
      window.clearInterval(timer)
    }
  }, [refresh])

  // Invalidate during render, before an effect runs: account A's grants must
  // never be visible for even one frame after switching to account B/signing out.
  const current = identityReady && snapshot?.identity === scopedIdentity && snapshot.generation === generation
    ? snapshot : null
  const features = current?.features ?? EMPTY_FEATURES
  const error = sessionError ? 'Could not verify your session' : current?.error ?? null
  const loading = !current && !error
  const loaded = Boolean(current && !current.error)
  const can = useCallback((key: string) => isFeatureAllowed(features, key), [features])
  const value = useMemo(() => ({ features, loading, loaded, error, can, refresh }),
    [features, loading, loaded, error, can, refresh])

  return <EntitlementsContext.Provider value={value}>{children}</EntitlementsContext.Provider>
}

export function useEntitlements(): EntitlementsContextValue {
  return useContext(EntitlementsContext)
}
