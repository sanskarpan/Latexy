'use client'

import { useEffect } from 'react'

import { recordPortfolioView } from '@/lib/analytics/portfolio'
import { ANALYTICS_CONSENT_EVENT, type AnalyticsConsent } from '@/lib/analytics/posthog'

/**
 * First-party portfolio view capture. The transport checks analytics consent
 * before sending anything, and the containing public page stays inside the
 * PostHog `ph-no-capture` boundary.
 */
export default function PortfolioAnalytics({ username }: { username: string }) {
  useEffect(() => {
    void recordPortfolioView(username)
    const onConsent = (event: Event) => {
      if ((event as CustomEvent<AnalyticsConsent>).detail === 'granted') {
        void recordPortfolioView(username)
      }
    }
    window.addEventListener(ANALYTICS_CONSENT_EVENT, onConsent)
    return () => window.removeEventListener(ANALYTICS_CONSENT_EVENT, onConsent)
  }, [username])

  return null
}
