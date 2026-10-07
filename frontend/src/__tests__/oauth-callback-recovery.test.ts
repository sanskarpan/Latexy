import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'
import { google } from 'better-auth/social-providers'
import { mapOAuthCallbackError, oauthErrorCallbackURL } from '@/lib/oauth-callback'

const signInSource = readFileSync(
  new URL('../components/auth/SignInForm.tsx', import.meta.url),
  'utf8',
)
const signUpSource = readFileSync(
  new URL('../components/auth/SignUpForm.tsx', import.meta.url),
  'utf8',
)
const loginSource = readFileSync(new URL('../app/login/page.tsx', import.meta.url), 'utf8')
const signupSource = readFileSync(new URL('../app/signup/page.tsx', import.meta.url), 'utf8')

describe('OAuth callback recovery', () => {
  it('maps known callback failures without reflecting provider descriptions', () => {
    const providerDescription = 'attacker-controlled secret: do not display this'

    expect(mapOAuthCallbackError('access_denied')).toMatch(/canceled|cancelled/i)
    expect(mapOAuthCallbackError('account_not_linked')).toMatch(/link/i)
    expect(mapOAuthCallbackError('state_mismatch')).toMatch(/expired|again/i)
    expect(mapOAuthCallbackError('expired')).toMatch(/expired|again/i)

    expect(mapOAuthCallbackError('provider_unknown_error')).toMatch(/sign-in|try again/i)
    expect(mapOAuthCallbackError(`provider_unknown_error:${providerDescription}`)).not.toContain(
      providerDescription,
    )
    expect(mapOAuthCallbackError('')).toBe('')
  })

  it('passes a validated same-origin error callback and renders callback errors', () => {
    expect(oauthErrorCallbackURL('/login', '/workspace?tab=recent')).toBe(
      '/login?redirect=%2Fworkspace%3Ftab%3Drecent',
    )
    expect(oauthErrorCallbackURL('/signup', '/workspace')).toBe('/signup?redirect=%2Fworkspace')
    expect(oauthErrorCallbackURL('/login', 'https://evil.example/steal')).not.toContain('evil.example')
    expect(oauthErrorCallbackURL('/login', '//evil.example/steal')).not.toContain('evil.example')
    expect(oauthErrorCallbackURL('/login', '/\\evil.example/steal')).not.toContain('evil.example')
    for (const unsafe of ['/\nevil.example', '/\revil.example', '/\tevil.example', '/x\\evil.example']) {
      expect(oauthErrorCallbackURL('/login', unsafe)).toBe('/login?redirect=%2Fworkspace')
    }
    expect(oauthErrorCallbackURL('/login', '/workspace?tab=recent#oauth')).toBe(
      '/login?redirect=%2Fworkspace%3Ftab%3Drecent%23oauth',
    )
    for (const source of [signInSource, signUpSource]) {
      expect(source).toContain('errorCallbackURL')
      expect(source).toMatch(/oauth-callback|oauthCallback|OAuthCallback/)
    }
    for (const source of [loginSource, signupSource]) {
      expect(source).toContain('useSearchParams')
      expect(source).toContain('oauthError')
      expect(source).toMatch(/oauthError=\{oauthError\}/)
    }
  })

  it('uses Better Auth Google basic identity scopes and the canonical callback', async () => {
    const provider = google({ clientId: 'synthetic-google-id', clientSecret: 'synthetic-google-secret' })
    const authorizationURL = await provider.createAuthorizationURL({
      state: 'synthetic-state',
      codeVerifier: 'synthetic-verifier',
      redirectURI: 'https://latexy.xyz/api/auth/callback/google',
    })
    const url = new URL(authorizationURL)

    expect(url.origin).toBe('https://accounts.google.com')
    expect(url.pathname).toBe('/o/oauth2/v2/auth')
    expect(url.searchParams.get('redirect_uri')).toBe('https://latexy.xyz/api/auth/callback/google')
    expect(url.searchParams.get('scope')?.split(' ').sort()).toEqual(['email', 'openid', 'profile'])
    expect(url.searchParams.get('scope')).not.toMatch(/drive|gmail/i)
  })
})
