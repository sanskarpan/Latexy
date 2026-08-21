import { useState, useEffect, useCallback } from 'react'
import { apiClient, getDeviceFingerprint } from '@/lib/api-client'

export interface TrialStatus {
  used: number
  total: number
  blocked: boolean
  remaining: number
  canRun: boolean
  fingerprint: string
}

const DEFAULT_TOTAL = 3

export function useTrialStatus() {
  // `fingerprint` must NEVER start empty: getDeviceFingerprint() reads/writes
  // localStorage synchronously, so it is always available on first render —
  // there is no need to wait for the async trial-status fetch below to
  // populate it. Previously this state initialized to '', and callers that
  // read `trialStatus.fingerprint` (e.g. the /try compile button, autosave)
  // could fire before `fetchStatus` resolved, sending device_fingerprint=''
  // and permanently 400ing a brand-new visitor's very first compile
  // ("device_fingerprint is required for anonymous jobs."). Seeding it from
  // the same synchronous source `fetchStatus` itself uses closes that race.
  const [status, setStatus] = useState<TrialStatus>(() => ({
    used: 0,
    total: DEFAULT_TOTAL,
    blocked: false,
    remaining: DEFAULT_TOTAL,
    canRun: true,
    fingerprint: getDeviceFingerprint(),
  }))
  const [loading, setLoading] = useState(true)

  const fetchStatus = useCallback(async () => {
    const fp = getDeviceFingerprint()
    try {
      const res = await apiClient.getTrialStatus(fp)
      const used = res.usageCount
      // Prefer server-supplied trialLimit (test users get 100), fall back to 3
      const total = (res as { trialLimit?: number }).trialLimit ?? DEFAULT_TOTAL
      setStatus({
        used,
        total,
        blocked: res.blocked,
        remaining: Math.max(0, total - used),
        canRun: !res.blocked && used < total,
        fingerprint: fp,
      })
      // Cache for offline/immediate checks (include total so test users retain correct limit)
      localStorage.setItem('trial_usage', JSON.stringify({ used, total }))
    } catch {
      // Fallback to cache — guard against corrupted/truncated JSON.
      const cached = localStorage.getItem('trial_usage')
      if (cached) {
        try {
          const { used, total = DEFAULT_TOTAL } = JSON.parse(cached)
          setStatus((prev) => ({
            ...prev,
            used,
            total,
            remaining: Math.max(0, total - used),
            canRun: used < total,
            fingerprint: fp,
          }))
        } catch {
          // Corrupted cache — drop it and keep defaults.
          localStorage.removeItem('trial_usage')
        }
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchStatus()
  }, [fetchStatus])

  const incrementUsage = useCallback(() => {
    setStatus((prev) => {
      const newUsed = prev.used + 1
      const updated = {
        ...prev,
        used: newUsed,
        remaining: Math.max(0, prev.total - newUsed),
        canRun: !prev.blocked && newUsed < prev.total,
      }
      localStorage.setItem('trial_usage', JSON.stringify({ used: updated.used, total: updated.total }))
      return updated
    })
  }, [])

  return { ...status, loading, refresh: fetchStatus, incrementUsage }
}
