/**
 * Consent-gated public portfolio performance transport.
 *
 * Nothing here runs unless the visitor granted analytics consent. The payload
 * contains only an explicit consent attestation and the public portfolio
 * username from the route. The backend derives a short hashed viewer key,
 * referrer host, and country; no IP, user-agent, email, name, message, or
 * document content is ever sent or returned.
 */

import { readAnalyticsConsent } from './posthog'

const API_BASE =
  (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_API_URL) ||
  'http://localhost:8030'

const USERNAME_PATTERN = /^[A-Za-z0-9_-]{3,30}$/

export const PORTFOLIO_VIEW_PATH = (username: string) =>
  `/portfolio/${encodeURIComponent(username)}/analytics/view`
export const PORTFOLIO_CONTACT_PATH = (username: string) =>
  `/portfolio/${encodeURIComponent(username)}/analytics/contact`
export const PORTFOLIO_SIGNUP_CLAIM_PATH = '/portfolio/analytics/claim-signup'

export interface PortfolioCaptureResult {
  recorded?: boolean
  reason?: string
  action?: string
}

export function canCapturePortfolioAnalytics(): boolean {
  return typeof window !== 'undefined' && readAnalyticsConsent() === 'granted'
}

function validUsername(username: string): boolean {
  return USERNAME_PATTERN.test(username)
}

async function postCapture(
  path: string,
  headers?: Record<string, string>,
): Promise<PortfolioCaptureResult | null> {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...headers,
      },
      body: JSON.stringify({ analytics_consent: true }),
      credentials: 'include',
      keepalive: true,
    })
    if (!response.ok) return null
    return (await response.json().catch(() => ({}))) as PortfolioCaptureResult
  } catch {
    // Analytics must never break the public portfolio or contact flow.
    return null
  }
}

export async function recordPortfolioView(
  username: string,
): Promise<PortfolioCaptureResult | null> {
  if (!validUsername(username) || !canCapturePortfolioAnalytics()) return null
  return postCapture(PORTFOLIO_VIEW_PATH(username))
}

export async function recordPortfolioContact(
  username: string,
): Promise<PortfolioCaptureResult | null> {
  if (!validUsername(username) || !canCapturePortfolioAnalytics()) return null
  return postCapture(PORTFOLIO_CONTACT_PATH(username))
}

/**
 * After signup, ask the backend to match this account to an earlier consented
 * portfolio visit using the same short viewer key. The backend owns the match
 * and only copies the public portfolio owner label.
 */
export async function claimPortfolioSignup(
  token: string | null | undefined,
): Promise<boolean> {
  if (!token) return false
  if (!canCapturePortfolioAnalytics()) return false
  if (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_PLAYWRIGHT_TEST === '1') {
    return false
  }
  const result = await postCapture(PORTFOLIO_SIGNUP_CLAIM_PATH, {
    Authorization: `Bearer ${token}`,
  })
  return result?.recorded === true
}
