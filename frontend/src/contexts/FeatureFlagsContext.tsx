'use client'

import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { loadExperimentAssignments } from '@/lib/analytics/experiments'
import { recordFlagExposures } from '@/lib/analytics/flag-exposure'

export interface FeatureFlags {
  trial_limits: boolean
  deep_analysis_trial: boolean
  compile_timeouts: boolean
  task_priority: boolean
  billing: boolean
  upgrade_ctas: boolean
}

const DEFAULT_FLAGS: FeatureFlags = {
  trial_limits: true,
  deep_analysis_trial: true,
  compile_timeouts: true,
  task_priority: true,
  billing: true,
  upgrade_ctas: true,
}

const KNOWN_FLAG_KEYS = Object.keys(DEFAULT_FLAGS) as Array<keyof FeatureFlags>

const FeatureFlagsContext = createContext<FeatureFlags>(DEFAULT_FLAGS)

export function FeatureFlagsProvider({ children }: { children: ReactNode }) {
  const [flags, setFlags] = useState<FeatureFlags>(DEFAULT_FLAGS)

  useEffect(() => {
    const API_BASE =
      process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'
    let cancelled = false

    fetch(`${API_BASE}/config/feature-flags`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data || typeof data !== 'object') return undefined
        const safe = KNOWN_FLAG_KEYS.reduce((acc, key) => {
          if (key in data && typeof data[key] === 'boolean') acc[key] = data[key] as boolean
          return acc
        }, {} as Partial<FeatureFlags>)
        setFlags((prev) => ({ ...prev, ...safe }))
        // Only server-returned values are reported; defaults are not an
        // evaluation. The server enforces consent and daily deduplication.
        recordFlagExposures(safe)

        // Assignment is consent-gated and deduped server-side. Only allowlisted
        // operational flags that the server already returned can be overridden,
        // so an experiment cannot introduce a capability the plan did not grant.
        return loadExperimentAssignments().then((overrides) => {
          if (cancelled || !overrides) return
          const applied = KNOWN_FLAG_KEYS.reduce((acc, key) => {
            if (key in safe && typeof overrides[key] === 'boolean') {
              acc[key] = overrides[key] as boolean
            }
            return acc
          }, {} as Partial<FeatureFlags>)
          if (Object.keys(applied).length > 0) setFlags((prev) => ({ ...prev, ...applied }))
        })
      })
      .catch(() => {
        // Non-critical — keep defaults (all enabled)
      })

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <FeatureFlagsContext.Provider value={flags}>
      {children}
    </FeatureFlagsContext.Provider>
  )
}

export function useFeatureFlags(): FeatureFlags {
  return useContext(FeatureFlagsContext)
}
