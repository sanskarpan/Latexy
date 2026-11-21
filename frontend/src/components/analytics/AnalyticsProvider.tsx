'use client'

import { useEffect, useRef, useState } from 'react'
import { usePathname } from 'next/navigation'
import { useSession } from '@/lib/auth-client'
import {
  ANALYTICS_CONSENT_EVENT,
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
    if (stored === 'granted') activate(pathname)

    const onConsent = (event: Event) => {
      const detail = (event as CustomEvent<AnalyticsConsent>).detail ?? null
      setConsent(detail)
      if (detail === 'granted') {
        activate(pathname)
      } else {
        setInitialized(false)
        lastTrackedPath.current = null
        disableAnalytics()
      }
    }
    window.addEventListener(ANALYTICS_CONSENT_EVENT, onConsent)
    return () => window.removeEventListener(ANALYTICS_CONSENT_EVENT, onConsent)
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
      identifyAnalyticsUser({
        id: user.id,
        role: (user as { role?: string }).role,
        createdAt: user.createdAt,
      })
    } else {
      resetAnalyticsUser()
    }
  }, [ready, consent, initialized, session?.user])

  if (!isAnalyticsConfigured() || consent !== null) return null
  return <AnalyticsConsentBanner />
}
