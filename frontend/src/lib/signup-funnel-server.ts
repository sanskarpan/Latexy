/**
 * Server-side OAuth callback failure counter.
 *
 * Runs inside the Better Auth route, where the callback path is authoritative.
 * The provider is therefore derived on the server (never from a browser
 * claim), and the only values written are the allowlisted provider bucket and
 * a coarse failure code. OAuth error descriptions, tokens, emails and names are
 * never read from the response or persisted.
 */

import type { Pool } from 'pg'

export type OAuthCallbackProvider = 'google' | 'github' | 'oidc'
export type OAuthCallbackFailureCode =
  | 'access_denied'
  | 'account_not_linked'
  | 'callback_failed'
  | 'provider_error'
  | 'state_mismatch'
  | 'unknown'

const CALLBACK_PATH = /^\/api\/auth\/callback\/([a-z0-9][a-z0-9_-]{1,63})$/

export function providerFromCallbackPath(pathname: string): OAuthCallbackProvider | null {
  const match = CALLBACK_PATH.exec(pathname)
  if (!match) return null
  const providerId = match[1]
  if (providerId === 'credential') return null
  if (providerId === 'google' || providerId === 'github') return providerId
  // Better Auth's generic OAuth plugin accepts an operator-configured provider
  // id (an institution's SSO). Bucket it as oidc instead of storing it raw.
  return 'oidc'
}

function errorCodeFromResponse(response: Response): string {
  if (response.status >= 300 && response.status < 400) {
    const location = response.headers.get('location')
    if (location) {
      try {
        return new URL(location, 'https://latexy.invalid').searchParams.get('error') ?? ''
      } catch {
        return ''
      }
    }
  }
  return ''
}

export function oauthFailureCodeFromResponse(response: Response): OAuthCallbackFailureCode {
  const code = errorCodeFromResponse(response).toLowerCase()
  if (!code) return 'callback_failed'
  if (code === 'access_denied') return 'access_denied'
  if (code === 'account_not_linked') return 'account_not_linked'
  if (code.includes('state')) return 'state_mismatch'
  if (code === 'provider_error' || code === 'server_error' || code === 'temporarily_unavailable') {
    return 'provider_error'
  }
  return 'unknown'
}

export function isOAuthCallbackFailure(response: Response): boolean {
  if (response.status >= 400) return true
  if (response.status >= 300 && response.status < 400) {
    return errorCodeFromResponse(response).length > 0
  }
  return false
}

export async function recordOAuthCallbackFailure(
  pool: Pick<Pool, 'query'>,
  pathname: string,
  response: Response,
): Promise<void> {
  const provider = providerFromCallbackPath(pathname)
  if (!provider || !isOAuthCallbackFailure(response)) return
  try {
    await pool.query(
      "INSERT INTO signup_funnel_events (id, event, provider, failure_code, created_at) "
        + "VALUES ($1, 'oauth_failure', $2, $3, now())",
      [crypto.randomUUID(), provider, oauthFailureCodeFromResponse(response)],
    )
  } catch {
    // Failure analytics must never break the OAuth callback response.
  }
}
