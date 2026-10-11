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

export const ENTITLEMENT_REFRESH_MS = 30_000
export const ENTITLEMENT_REQUEST_TIMEOUT_MS = 8_000
export const ENTITLEMENT_MAX_AGE_MS = ENTITLEMENT_REFRESH_MS + ENTITLEMENT_REQUEST_TIMEOUT_MS

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
  invalidation: number
  verifiedAt: number
  features: Record<string, boolean>
  error: string | null
}

export function EntitlementsProvider({ children }: { children: ReactNode }) {
  const { data: session, isPending, error: sessionError } = useSession()
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [generation, setGeneration] = useState({ request: 0, invalidation: 0 })
  const identity = session?.user?.id ? `user:${session.user.id}` : 'anonymous'
  const identityReady = !isPending && !sessionError
  const scopeRef = useRef({ identity, ready: identityReady, epoch: 0 })
  if (scopeRef.current.identity !== identity || scopeRef.current.ready !== identityReady) {
    scopeRef.current = { identity, ready: identityReady, epoch: scopeRef.current.epoch + 1 }
  }
  const scopedIdentity = `${identity}:${scopeRef.current.epoch}`
  const refresh = useCallback(() => setGeneration((n) => ({ request: n.request + 1, invalidation: n.invalidation + 1 })), [])
  const backgroundRefresh = useCallback(() => setGeneration((n) => ({ ...n, request: n.request + 1 })), [])

  useEffect(() => {
    if (!identityReady) return
    let active = true
    const controller = new AbortController()
    const deny = (error: string) => {
      if (!active) return
      active = false
      controller.abort()
      setSnapshot({ identity: scopedIdentity, invalidation: generation.invalidation,
        verifiedAt: Date.now(), features: EMPTY_FEATURES, error })
    }
    const timeout = window.setTimeout(() => deny('Feature availability check timed out'), ENTITLEMENT_REQUEST_TIMEOUT_MS)
    // Same-identity background refresh preserves verified grants only for the
    // bounded freshness window. Explicit invalidation never preserves them.
    apiClient.getEntitlements(controller.signal).then((data) => {
      const features = parseEffectiveFeatures(data?.features)
      if (active) setSnapshot({ identity: scopedIdentity, invalidation: generation.invalidation,
        verifiedAt: Date.now(), features, error: null })
    }).catch((err: unknown) => {
      deny(err instanceof Error ? err.message : 'Could not load feature availability')
    }).finally(() => window.clearTimeout(timeout))
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [scopedIdentity, identityReady, generation])

  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === 'visible') backgroundRefresh() }
    window.addEventListener('focus', backgroundRefresh)
    window.addEventListener('latexy:entitlements-updated', refresh)
    document.addEventListener('visibilitychange', onVisible)
    const timer = window.setInterval(onVisible, ENTITLEMENT_REFRESH_MS)
    return () => {
      window.removeEventListener('focus', backgroundRefresh)
      window.removeEventListener('latexy:entitlements-updated', refresh)
      document.removeEventListener('visibilitychange', onVisible)
      window.clearInterval(timer)
    }
  }, [refresh, backgroundRefresh])

  useEffect(() => {
    if (!snapshot || snapshot.error) return
    const timeout = window.setTimeout(() => {
      setSnapshot((current) => current === snapshot ? { ...current, features: EMPTY_FEATURES,
        error: 'Feature availability expired. Please retry.' } : current)
    }, Math.max(0, snapshot.verifiedAt + ENTITLEMENT_MAX_AGE_MS - Date.now()))
    return () => window.clearTimeout(timeout)
  }, [snapshot])

  // Invalidate during render, before an effect runs: account A's grants must
  // never be visible for even one frame after switching to account B/signing out.
  const current = identityReady && snapshot?.identity === scopedIdentity && snapshot.invalidation === generation.invalidation
    && (snapshot.error || Date.now() - snapshot.verifiedAt < ENTITLEMENT_MAX_AGE_MS)
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
