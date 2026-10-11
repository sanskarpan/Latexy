'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useSession } from '@/lib/auth-client'
import { apiClient, type UserRole } from '@/lib/api-client'

const REFRESH_MS = 30_000
const TIMEOUT_MS = 8_000

/** Account roles never come from a prior identity or an unverified session. */
export function useAccountRole() {
  const { data: session, isPending, error: sessionError } = useSession()
  const userId = session?.user?.id ?? null
  const ready = !isPending && !sessionError && Boolean(userId)
  const scopeRef = useRef({ userId, ready, epoch: 0 })
  if (scopeRef.current.userId !== userId || scopeRef.current.ready !== ready) {
    scopeRef.current = { userId, ready, epoch: scopeRef.current.epoch + 1 }
  }
  const scopeKey = `${userId ?? 'anonymous'}:${scopeRef.current.epoch}`
  const [generation, setGeneration] = useState(0)
  const [snapshot, setSnapshot] = useState<{ scopeKey: string; role: UserRole | null; error: string | null; verifiedAt: number } | null>(null)
  const refresh = useCallback(() => setGeneration((value) => value + 1), [])
  useEffect(() => {
    if (!ready) return
    let active = true
    const deny = (message: string) => {
      if (!active) return
      active = false
      setSnapshot({ scopeKey, role: null, error: message, verifiedAt: Date.now() })
    }
    const timer = window.setTimeout(() => deny('Account access check timed out'), TIMEOUT_MS)
    apiClient.getMe().then((account) => {
      if (!active) return
      if (account.id !== userId || !['user', 'support', 'admin'].includes(account.role)) {
        deny('Could not verify account access')
        return
      }
      setSnapshot({ scopeKey, role: account.role, error: null, verifiedAt: Date.now() })
    }).catch(() => deny('Could not verify account access')).finally(() => window.clearTimeout(timer))
    return () => { active = false; window.clearTimeout(timer) }
  }, [scopeKey, ready, userId, generation])
  useEffect(() => {
    const visible = () => { if (document.visibilityState === 'visible') refresh() }
    window.addEventListener('focus', visible)
    window.addEventListener('latexy:account-role-updated', refresh)
    document.addEventListener('visibilitychange', visible)
    const timer = window.setInterval(visible, REFRESH_MS)
    return () => {
      window.removeEventListener('focus', visible)
      window.removeEventListener('latexy:account-role-updated', refresh)
      document.removeEventListener('visibilitychange', visible)
      window.clearInterval(timer)
    }
  }, [refresh])
  useEffect(() => {
    if (!snapshot || snapshot.error) return
    const timer = window.setTimeout(() => setSnapshot((current) => current === snapshot
      ? { ...current, role: null, error: 'Account access expired. Please retry.' } : current),
    Math.max(0, snapshot.verifiedAt + REFRESH_MS + TIMEOUT_MS - Date.now()))
    return () => window.clearTimeout(timer)
  }, [snapshot])
  const current = ready && snapshot?.scopeKey === scopeKey && (snapshot.error || Date.now() - snapshot.verifiedAt < REFRESH_MS + TIMEOUT_MS) ? snapshot : null
  return {
    role: current?.role ?? null,
    loading: isPending || (ready && !current),
    error: sessionError ? 'Could not verify your session' : current?.error ?? null,
    refresh,
    scopeKey,
  }
}
