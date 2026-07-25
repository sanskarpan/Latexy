'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  ReactNode,
} from 'react'
import { apiClient } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'

interface EntitlementsContextValue {
  /** Effective feature map for the current user (empty until loaded). */
  features: Record<string, boolean>
  loading: boolean
  loaded: boolean
  /**
   * Whether the given feature key is available to the current user.
   *
   * Fail-open: returns TRUE while loading, on error, or for unknown/
   * non-gateable keys — never hide a working feature. Only returns false
   * when the backend has explicitly reported the feature as disabled.
   */
  can: (featureKey: string) => boolean
  refresh: () => void
}

const EntitlementsContext = createContext<EntitlementsContextValue>({
  features: {},
  loading: false,
  loaded: false,
  can: () => true,
  refresh: () => {},
})

export function EntitlementsProvider({ children }: { children: ReactNode }) {
  const { data: session } = useSession()
  const [features, setFeatures] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [nonce, setNonce] = useState(0)

  const userId = session?.user?.id ?? null

  useEffect(() => {
    // Only fetch the per-user entitlement map once a session is present.
    // Anonymous users fail-open on the frontend (can() returns true); the
    // backend still enforces the free-plan map on every request.
    if (!userId) {
      setFeatures({})
      setLoaded(false)
      return
    }

    let cancelled = false
    setLoading(true)
    apiClient
      .getEntitlements()
      .then((data) => {
        if (cancelled) return
        setFeatures(data?.features ?? {})
        setLoaded(true)
      })
      .catch(() => {
        // Fail-open — keep whatever we had; can() defaults to true.
        if (!cancelled) setLoaded(true)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [userId, nonce])

  const can = useCallback(
    (featureKey: string): boolean => {
      // Fail-open: unknown key or not-yet-loaded → allowed.
      const value = features[featureKey]
      return value === undefined ? true : value
    },
    [features],
  )

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  const value = useMemo<EntitlementsContextValue>(
    () => ({ features, loading, loaded, can, refresh }),
    [features, loading, loaded, can, refresh],
  )

  return (
    <EntitlementsContext.Provider value={value}>
      {children}
    </EntitlementsContext.Provider>
  )
}

export function useEntitlements(): EntitlementsContextValue {
  return useContext(EntitlementsContext)
}
