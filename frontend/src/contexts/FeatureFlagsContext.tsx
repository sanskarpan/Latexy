'use client'

import { createContext, useContext, useEffect, useState, ReactNode } from 'react'

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

const FeatureFlagsContext = createContext<FeatureFlags>(DEFAULT_FLAGS)

export function FeatureFlagsProvider({ children }: { children: ReactNode }) {
  const [flags, setFlags] = useState<FeatureFlags>(DEFAULT_FLAGS)

  useEffect(() => {
    const API_BASE =
      process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

    fetch(`${API_BASE}/config/feature-flags`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data && typeof data === 'object') {
          setFlags((prev) => ({ ...prev, ...data }))
        }
      })
      .catch(() => {
        // Non-critical — keep defaults (all enabled)
      })
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
