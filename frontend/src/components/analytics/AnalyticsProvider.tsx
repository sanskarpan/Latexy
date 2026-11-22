'use client'

import { useEffect, useRef, useState } from 'react'
import { usePathname } from 'next/navigation'
import { useSession } from '@/lib/auth-client'
import {
  ANALYTICS_CONSENT_EVENT,
  ANALYTICS_CONSENT_KEY,
  capturePageview,
  disableAnalytics,
  identifyAnalyticsUser,
  initializeAnalytics,
  isAnalyticsConfigured,
  readAnalyticsConsent,
  resetAnalyticsUser,
  type AnalyticsConsent,
} from '@/lib/analytics/posthog'
import AnalyticsConsentBanner from './AnalyticsConsentBanner'

/**
 * Mounts once at the root. It is deliberately inert until the visitor grants
 * analytics consent, and it re-checks consent on every route change.
 */
export default function AnalyticsProvider() {
  const pathname = usePathname()
  const { data: session } = useSession()
  const [consent, setConsent] = useState<AnalyticsConsent>(null)
  const [ready, setReady] = useState(false)
  const [initialized, setInitialized] = useState(false)
  const lastTrackedPath = useRef<string | null>(null)
  const pathnameRef = useRef(pathname)
  const identifiedUserId = useRef<string | null>(null)

  useEffect(() => {
    pathnameRef.current = pathname
  }, [pathname])

  const activate = (path: string) => {
    void initializeAnalytics().then((ok) => {
      if (!ok) return
      setInitialized(true)
      if (lastTrackedPath.current !== path) {
        lastTrackedPath.current = path
        capturePageview(path)
      }
    })
  }

  useEffect(() => {
    const stored = readAnalyticsConsent()
    setConsent(stored)
    setReady(true)
    if (stored === 'granted') activate(pathnameRef.current)

    const applyConsent = (next: AnalyticsConsent) => {
      setConsent(next)
      if (next === 'granted') {
        activate(pathnameRef.current)
      } else {
        setInitialized(false)
        lastTrackedPath.current = null
        identifiedUserId.current = null
        disableAnalytics()
      }
    }
    const onConsent = (event: Event) => {
      applyConsent((event as CustomEvent<AnalyticsConsent>).detail ?? null)
    }
    // Consent may be withdrawn or granted in another tab. Keep open tabs from
    // capturing after a withdrawal even before the next reload.
    const onStorage = (event: StorageEvent) => {
      if (event.key !== ANALYTICS_CONSENT_KEY && event.key !== null) return
      applyConsent(readAnalyticsConsent())
    }
    window.addEventListener(ANALYTICS_CONSENT_EVENT, onConsent)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(ANALYTICS_CONSENT_EVENT, onConsent)
      window.removeEventListener('storage', onStorage)
    }
    // The initial path is read once; later path changes are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!ready || consent !== 'granted' || !initialized) return
    if (lastTrackedPath.current === pathname) return
    lastTrackedPath.current = pathname
    capturePageview(pathname)
  }, [pathname, ready, consent, initialized])

  useEffect(() => {
    if (!ready || consent !== 'granted' || !initialized) return
    const user = session?.user
    if (user?.id) {
      // Reset between distinct accounts so a shared device's anonymous
      // $device_id does not silently link the previous person's events.
      if (identifiedUserId.current && identifiedUserId.current !== user.id) {
        resetAnalyticsUser()
      }
      identifiedUserId.current = user.id
      identifyAnalyticsUser({
        id: user.id,
        role: (user as { role?: string }).role,
        createdAt: user.createdAt,
      })
    } else {
      identifiedUserId.current = null
      resetAnalyticsUser()
    }
  }, [ready, consent, initialized, session?.user])

  if (!isAnalyticsConfigured() || consent !== null) return null
  return <AnalyticsConsentBanner />
}
