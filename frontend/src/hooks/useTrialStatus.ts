import { useState, useEffect, useCallback } from 'react'
import { apiClient, generateDeviceFingerprint } from '@/lib/api-client'

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
  const [status, setStatus] = useState<TrialStatus>({
    used: 0,
    total: DEFAULT_TOTAL,
    blocked: false,
    remaining: DEFAULT_TOTAL,
    canRun: true,
    fingerprint: '',
  })
  const [loading, setLoading] = useState(true)

  const fetchStatus = useCallback(async () => {
    const fp = generateDeviceFingerprint()
    try {
      const res = await apiClient.getTrialStatus(fp)
      const used = res.usageCount
      const total = DEFAULT_TOTAL
      setStatus({
        used,
        total,
        blocked: res.blocked,
        remaining: Math.max(0, total - used),
        canRun: !res.blocked && used < total,
        fingerprint: fp,
      })
      // Cache for offline/immediate checks
      localStorage.setItem('trial_usage', JSON.stringify({ used, total }))
    } catch (err) {
      // Fallback to cache
      const cached = localStorage.getItem('trial_usage')
      if (cached) {
        const { used, total } = JSON.parse(cached)
        setStatus((prev) => ({
          ...prev,
          used,
          total,
          remaining: Math.max(0, total - used),
          canRun: used < total,
          fingerprint: fp,
        }))
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
