import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'

import {
  isOAuthCallbackFailure,
  oauthFailureCodeFromResponse,
  providerFromCallbackPath,
  recordOAuthCallbackFailure,
} from '../lib/signup-funnel-server'

const routeSource = readFileSync(
  new URL('../app/api/auth/[...all]/route.ts', import.meta.url),
  'utf8',
)

function redirect(location: string, status = 302): Response {
  return new Response(null, { status, headers: { location } })
}

describe('server-derived signup OAuth failure counters', () => {
  it('derives allowlisted providers only from the callback path', () => {
    expect(providerFromCallbackPath('/api/auth/callback/google')).toBe('google')
    expect(providerFromCallbackPath('/api/auth/callback/github')).toBe('github')
    expect(providerFromCallbackPath('/api/auth/callback/acme-university-sso')).toBe('oidc')
    expect(providerFromCallbackPath('/api/auth/callback/credential')).toBeNull()
    expect(providerFromCallbackPath('/api/auth/sign-in/social')).toBeNull()
    expect(providerFromCallbackPath('/api/auth/callback/')).toBeNull()
    expect(providerFromCallbackPath('/api/auth/callback/../../admin')).toBeNull()
  })

  it('recognizes callback redirects and HTTP failures without reading bodies', () => {
    expect(isOAuthCallbackFailure(redirect('/signup?error=access_denied'))).toBe(true)
    expect(isOAuthCallbackFailure(redirect('/login?error=state_mismatch'))).toBe(true)
    expect(isOAuthCallbackFailure(redirect('/workspace'))).toBe(false)
    expect(isOAuthCallbackFailure(new Response(null, { status: 200 }))).toBe(false)
    expect(isOAuthCallbackFailure(new Response(null, { status: 500 }))).toBe(true)
  })

  it('maps provider error codes onto the coarse allowlist', () => {
    expect(oauthFailureCodeFromResponse(redirect('/signup?error=access_denied'))).toBe('access_denied')
    expect(oauthFailureCodeFromResponse(redirect('/signup?error=account_not_linked'))).toBe(
      'account_not_linked',
    )
    expect(oauthFailureCodeFromResponse(redirect('/signup?error=state_security_mismatch'))).toBe(
      'state_mismatch',
    )
    expect(oauthFailureCodeFromResponse(redirect('/signup?error=server_error'))).toBe('provider_error')
    expect(oauthFailureCodeFromResponse(redirect('/signup?error=some_new_code'))).toBe('unknown')
    expect(oauthFailureCodeFromResponse(new Response(null, { status: 500 }))).toBe('callback_failed')
  })

  it('writes only event, provider and failure code for a failed Google callback', async () => {
    const query = vi.fn().mockResolvedValue(undefined)
    await recordOAuthCallbackFailure(
      { query } as never,
      '/api/auth/callback/google',
      redirect('/signup?error=access_denied&error_description=token%3Dsecret'),
    )
    expect(query).toHaveBeenCalledTimes(1)
    const [sql, params] = query.mock.calls[0]
    expect(sql).toContain("'oauth_failure'")
    expect(params[1]).toBe('google')
    expect(params[2]).toBe('access_denied')
    expect(JSON.stringify(params)).not.toContain('token=secret')
    expect(JSON.stringify(params)).not.toContain('error_description')
  })

  it('never writes successful callbacks, non-callback paths, or analytics failures', async () => {
    const query = vi.fn().mockResolvedValue(undefined)
    await recordOAuthCallbackFailure({ query } as never, '/api/auth/callback/github', redirect('/workspace'))
    await recordOAuthCallbackFailure({ query } as never, '/api/auth/sign-in/social', redirect('/signup?error=x'))
    expect(query).not.toHaveBeenCalled()

    const failing = vi.fn().mockRejectedValue(new Error('db unavailable'))
    await expect(
      recordOAuthCallbackFailure({ query: failing } as never, '/api/auth/callback/github', new Response(null, { status: 500 })),
    ).resolves.toBeUndefined()
  })

  it('is wired into the Better Auth route after the handler', () => {
    expect(routeSource).toContain("from \"@/lib/signup-funnel-server\"")
    expect(routeSource).toContain('await auth.handler(request)')
    expect(routeSource).toContain('await recordOAuthCallbackFailure(pool, path, response)')
  })
})
