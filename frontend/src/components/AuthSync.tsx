'use client'

/**
 * AuthSync - keeps apiClient's auth token in sync with the Better Auth session.
 *
 * Mount once in the root layout (inside a Client Component boundary).
 * Whenever the Better Auth session changes (login, logout, token refresh)
 * apiClient is updated automatically so all subsequent API calls to FastAPI
 * include the correct Authorization: Bearer <session_token> header.
 */

import { useEffect, useRef } from 'react'
import { useSession } from '@/lib/auth-client'
import { apiClient, getDeviceFingerprint } from '@/lib/api-client'
import { wsClient } from '@/lib/ws-client'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'
import { readAnalyticsConsent } from '@/lib/analytics/posthog'
import {
  claimTrafficAttribution,
  hasPendingTrafficAttribution,
} from '@/lib/analytics/traffic-source'
import { claimTrialAttribution } from '@/lib/analytics/trial-attribution'
import { claimPortfolioSignup } from '@/lib/analytics/portfolio'

export function AuthSync() {
  const { data: session, isPending, isRefetching = false, error } = useSession()
  const referralClaimedFor = useRef<string | null>(null)
  const signupMilestonesFor = useRef<string | null>(null)
  const trafficClaimedFor = useRef<string | null>(null)
  const trialAttributionClaimedFor = useRef<string | null>(null)
  const portfolioSignupClaimedFor = useRef<string | null>(null)
  const unauthorized = isConfirmedSessionUnauthorized(error)

  useEffect(() => {
    // While the session request is in flight we know nothing yet — publishing a
    // null token here would open apiClient's auth-ready gate too early and let
    // mount-time fetches go out unauthenticated (401s that are never retried).
    // A non-401 failed refresh is not a confirmed logout. Preserve the last published
    // API/WS authentication state until Better Auth returns an authoritative
    // session or authoritative null response.
    if (!unauthorized && (isPending || isRefetching || error)) return
    // session?.session?.token is the raw Better Auth session token stored
    // in the `session` table. FastAPI validates it by querying that table.
    const token = unauthorized ? null : session?.session?.token ?? null
    apiClient.setAuthToken(token)
    // AuthSync is the single source of truth for "the session state is known",
    // so it is the only caller of markAuthResolved() — this is what releases
    // apiClient's auth-ready gate for anonymous visitors too.
    apiClient.markAuthResolved()
    // Tell the WS manager only whether it should mint an authenticated one-time
    // ticket. The reusable Better Auth token must never enter a WebSocket URL.
    wsClient.setAuthenticated(Boolean(token))
    if (!token) referralClaimedFor.current = null
    if (!token) signupMilestonesFor.current = null
    if (!token) trafficClaimedFor.current = null
    if (!token) trialAttributionClaimedFor.current = null
    if (!token) portfolioSignupClaimedFor.current = null

    // Server-derived signup funnel milestones: completion and (when the account
    // already has email_verified) verification. The backend ignores any client
    // provider and derives it from Better Auth's account rows; the call is
    // idempotent and must never block authentication or navigation.
    if (token && signupMilestonesFor.current !== token) {
      signupMilestonesFor.current = token
      void apiClient.recordSignupMilestones?.()
    }

    // First-touch UTM/referrer attribution is claimed from the server-stored
    // landing row, never from a client-supplied campaign. Only visitors who
    // granted analytics consent have a pending landing record.
    if (
      token &&
      trafficClaimedFor.current !== token &&
      hasPendingTrafficAttribution() &&
      readAnalyticsConsent() === 'granted'
    ) {
      trafficClaimedFor.current = token
      void claimTrafficAttribution(token)
    }

    // Link the anonymous trial on this device to the signed-in account only
    // when analytics consent was granted. The backend reads the campaign from
    // its own first-touch landing row and attaches the first paid subscription
    // when one exists. This is best-effort and never blocks sign-in.
    if (
      token &&
      trialAttributionClaimedFor.current !== token &&
      readAnalyticsConsent() === 'granted'
    ) {
      trialAttributionClaimedFor.current = token
      void claimTrialAttribution(token, getDeviceFingerprint())
    }

    // Link a new account to a consented portfolio visit using the same
    // server-derived viewer key. No client identifier or campaign value is
    // accepted; the backend performs the match and stores only the public
    // portfolio owner label. Best-effort and never blocks sign-in.
    if (
      token &&
      portfolioSignupClaimedFor.current !== token &&
      readAnalyticsConsent() === 'granted'
    ) {
      portfolioSignupClaimedFor.current = token
      void claimPortfolioSignup(token)
    }

    // Sign-up and OAuth both preserve the first-party referral cookie. Claim it
    // after Better Auth has issued a session so the backend, not the browser,
    // decides attribution. The proxy clears the cookie after this one attempt.
    if (token && referralClaimedFor.current !== token && document.cookie.split(';').some((item) => item.trim().startsWith('latexy_referral='))) {
      referralClaimedFor.current = token
      void fetch('/api/referral', { method: 'POST', credentials: 'include' }).catch(() => {
        // Referral capture must never block or fail authentication/navigation.
      })
    }
  }, [session, isPending, isRefetching, error, unauthorized])

  return null
}
