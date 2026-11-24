/**
 * Anonymous signup-attempt telemetry.
 *
 * These helpers deliberately avoid the authenticated ApiClient singleton: the
 * sign-up form mounts for signed-out visitors, and importing the API client
 * there pulls in tenant/cookie state that must not be needed to render auth.
 *
 * Only the six allowlisted provider labels ever leave the browser, and the
 * backend never uses them to attribute an account. Completion/verification
 * providers are always derived from server-owned auth state.
 */

import type { SignupAuthProvider, SignupOAuthFailureCode } from './api-client'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

export async function trackSignupStarted(provider?: SignupAuthProvider): Promise<void> {
  try {
    await fetch(`${API_BASE}/analytics/signup/started`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(provider ? { provider } : {}),
      credentials: 'include',
    })
  } catch {
    // Analytics must never block sign-up.
  }
}

export async function trackOAuthFailure(
  provider: SignupAuthProvider,
  failureCode: SignupOAuthFailureCode = 'callback_failed',
): Promise<void> {
  try {
    await fetch(`${API_BASE}/analytics/signup/oauth-failure`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, failure_code: failureCode }),
      credentials: 'include',
    })
  } catch {
    // Non-critical.
  }
}
