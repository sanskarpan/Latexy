import { generateKeyPairSync, sign } from 'node:crypto'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { betterAuth } from 'better-auth'
import { memoryAdapter } from 'better-auth/adapters/memory'
import { createAuthClient } from 'better-auth/client'
import { createInstitutionalOidcPlugin, normalizeInstitutionalOidcCallback } from '../lib/oidc-provider'
import { readOidcConfig } from '../lib/oidc-config'

const appUrl = 'https://latexy.example'
const issuer = 'https://id.example.edu'
const discoveryUrl = `${issuer}/.well-known/openid-configuration`
const configuration = () => readOidcConfig({
  OIDC_PROVIDER_ID: 'university_sso',
  OIDC_DISCOVERY_URL: discoveryUrl,
  OIDC_CLIENT_ID: 'test-client',
  OIDC_CLIENT_SECRET: 'test-client-secret',
  OIDC_ISSUER: issuer,
})!

function mockDiscovery(
  overrides: Record<string, unknown> = {},
  respond?: (url: string, init?: RequestInit) => Response,
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input)
    if (url === discoveryUrl) return Response.json({
      issuer,
      authorization_endpoint: `${issuer}/authorize`,
      token_endpoint: `${issuer}/token`,
      userinfo_endpoint: `${issuer}/userinfo`,
      jwks_uri: `${issuer}/jwks`,
      id_token_signing_alg_values_supported: ['RS256'],
      end_session_endpoint: `${issuer}/logout`,
      ...overrides,
    })
    if (respond) return respond(url, init)
    throw new Error(`Unexpected external request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function createTestAuth(existingAccount = false) {
  const createdAt = new Date('2026-01-01T00:00:00Z')
  return betterAuth({
    baseURL: appUrl,
    secret: 'test-only-upgrade-secret-at-least-thirty-two-characters',
    database: memoryAdapter({
      user: existingAccount ? [{ id: 'existing-user', email: 'oidc@example.edu', emailVerified: true, name: 'Existing User', createdAt, updatedAt: createdAt }] : [],
      account: existingAccount ? [{ id: 'existing-account', providerId: 'university_sso', accountId: 'existing-subject', userId: 'existing-user', createdAt, updatedAt: createdAt }] : [],
      session: [], verification: [],
    }),
    plugins: [createInstitutionalOidcPlugin(configuration(), appUrl)],
  })
}

afterEach(() => vi.unstubAllGlobals())

describe('Better Auth 1.7 compatibility', () => {
  it('loads the actual Latexy client without a removed plugin export', async () => {
    const { authClient } = await import('../lib/auth-client')
    expect(typeof authClient.signIn.social).toBe('function')
    expect(typeof authClient.signIn.passkey).toBe('function')
  })

  it('starts institutional sign-in through the real social client and keeps the registered callback', async () => {
    const fetchMock = mockDiscovery()
    const auth = createTestAuth()
    const client = createAuthClient({
      baseURL: appUrl,
      fetchOptions: {
        customFetchImpl: async (input, init) => auth.handler(new Request(input, init)),
      },
    })
    const response = await client.signIn.social({ provider: 'university_sso', callbackURL: '/workspace' })
    expect(response.error).toBeNull()
    const authorizationUrl = new URL(response.data!.url!)
    expect(authorizationUrl.origin).toBe(issuer)
    expect(authorizationUrl.searchParams.get('redirect_uri')).toBe(`${appUrl}/api/auth/oauth2/callback/university_sso`)
    expect(authorizationUrl.searchParams.get('code_challenge_method')).toBe('S256')
    expect(authorizationUrl.searchParams.get('nonce')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledOnce()
    const provider = (await auth.$context).socialProviders.find((item) => item.id === 'university_sso')!
    expect(await provider.createEndSessionURL?.({})).toBeNull()
  })

  it.each(['valid', 'wrong-nonce', 'missing-id-token'])('keeps the registered callback and verifies OIDC identity (%s)', async (identityCase) => {
    const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
    const jwk = { ...publicKey.export({ format: 'jwk' }), kid: 'test-key', alg: 'RS256', use: 'sig' }
    let nonce = ''
    let tokenRedirectURI: string | null = null
    const fetchMock = mockDiscovery({}, (url, init) => {
      if (url === `${issuer}/jwks`) return Response.json({ keys: [jwk] })
      if (url === `${issuer}/userinfo`) return Response.json({
        sub: 'existing-subject', email: 'oidc@example.edu', email_verified: true, name: 'Test OIDC',
      })
      if (url === `${issuer}/token`) {
        const params = new URLSearchParams(String(init?.body))
        tokenRedirectURI = params.get('redirect_uri')
        expect(params.get('code')).toBe('provider-code')
        expect(params.get('code_verifier')).toBeTruthy()
        const header = Buffer.from(JSON.stringify({ alg: 'RS256', kid: 'test-key' })).toString('base64url')
        const payload = Buffer.from(JSON.stringify({
          iss: issuer, aud: 'test-client', sub: 'existing-subject', nonce: identityCase === 'wrong-nonce' ? 'wrong-nonce' : nonce,
          email: 'oidc@example.edu', email_verified: true, name: 'Test OIDC',
          iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 300,
        })).toString('base64url')
        const signature = sign('RSA-SHA256', Buffer.from(`${header}.${payload}`), privateKey).toString('base64url')
        return Response.json({ access_token: 'test-access-token', token_type: 'Bearer', id_token: identityCase === 'missing-id-token' ? undefined : `${header}.${payload}.${signature}` })
      }
      throw new Error(`Unexpected external request: ${url}`)
    })
    const auth = createTestAuth(true)
    const start = await auth.handler(new Request(`${appUrl}/api/auth/sign-in/social`, {
      method: 'POST', headers: { origin: appUrl, 'content-type': 'application/json' },
      body: JSON.stringify({ provider: 'university_sso', callbackURL: '/workspace' }),
    }))
    expect(start.status).toBe(200)
    const authorizationUrl = new URL((await start.json()).url)
    nonce = authorizationUrl.searchParams.get('nonce')!
    const cookie = start.headers.getSetCookie().map((value) => value.split(';')[0]).join('; ')
    const callback = new URL(authorizationUrl.searchParams.get('redirect_uri')!)
    callback.searchParams.set('state', authorizationUrl.searchParams.get('state')!)
    callback.searchParams.set('code', 'provider-code')
    const finish = await auth.handler(normalizeInstitutionalOidcCallback(new Request(callback, {
      headers: { cookie },
    }), 'university_sso'))
    expect(finish.status).toBe(302)
    expect(fetchMock.mock.calls.some(([input]) => String(input) === `${issuer}/userinfo`)).toBe(false)
    expect(tokenRedirectURI).toBe(`${appUrl}/api/auth/oauth2/callback/university_sso`)
    if (identityCase !== 'valid') {
      expect(finish.headers.get('location')).toContain('error=')
      expect(finish.headers.get('set-cookie') || '').not.toContain('session_token=')
      return
    }
    expect(finish.headers.get('location')).toBe('/workspace')
    expect(finish.headers.get('set-cookie')).toContain('session_token=')
    const sessionCookie = finish.headers.getSetCookie().map((value) => value.split(';')[0]).join('; ')
    const session = await auth.api.getSession({ headers: new Headers({ cookie: sessionCookie }) })
    expect(session?.user.email).toBe('oidc@example.edu')
    expect(session?.user.id).toBe('existing-user')
    expect(session?.user.emailVerified).toBe(true)
  })

  it.each([false, true])('does not add direct client ID-token sign-in (supplied nonce=%s)', async (supplyNonce) => {
    const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
    const jwk = { ...publicKey.export({ format: 'jwk' }), kid: 'test-key', alg: 'RS256', use: 'sig' }
    mockDiscovery({}, (url) => {
      if (url === `${issuer}/jwks`) return Response.json({ keys: [jwk] })
      throw new Error(`Unexpected external request: ${url}`)
    })
    const header = Buffer.from(JSON.stringify({ alg: 'RS256', kid: 'test-key' })).toString('base64url')
    const payload = Buffer.from(JSON.stringify({
      iss: issuer, aud: 'test-client', sub: 'existing-subject', nonce: 'client-chosen',
      email: 'oidc@example.edu', email_verified: true, name: 'Test OIDC',
      iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 300,
    })).toString('base64url')
    const signature = sign('RSA-SHA256', Buffer.from(`${header}.${payload}`), privateKey).toString('base64url')
    const response = await createTestAuth().handler(new Request(`${appUrl}/api/auth/sign-in/social`, {
      method: 'POST', headers: { origin: appUrl, 'content-type': 'application/json' },
      body: JSON.stringify({
        provider: 'university_sso', callbackURL: '/workspace',
        idToken: { token: `${header}.${payload}.${signature}`, ...(supplyNonce ? { nonce: 'client-chosen' } : {}) },
      }),
    }))
    expect(response.status).toBeGreaterThanOrEqual(400)
    expect(response.headers.get('set-cookie') || '').not.toContain('session_token=')
  })

  it('rejects a discovery document that changes the configured issuer pin', async () => {
    mockDiscovery({ issuer: 'https://unexpected.example' })
    await expect(createTestAuth().$context).rejects.toThrow(/does not match OIDC_ISSUER/)
  })

  it('does not register an OIDC provider without verification metadata', async () => {
    mockDiscovery({ jwks_uri: undefined })
    const context = await createTestAuth().$context
    expect(context.socialProviders.some((item) => item.id === 'university_sso')).toBe(false)
  })

  it('routes only the configured legacy callback and leaves state, cookies, and POST bodies intact', async () => {
    const original = new Request(`${appUrl}/api/auth/oauth2/callback/university_sso?state=signed-state&code=auth-code`, {
      headers: { cookie: 'better-auth.oauth_state=signed-cookie' },
    })
    const normalized = normalizeInstitutionalOidcCallback(original, 'university_sso')
    expect(normalized.url).toBe(`${appUrl}/api/auth/callback/university_sso?state=signed-state&code=auth-code`)
    expect(normalized.headers.get('cookie')).toBe(original.headers.get('cookie'))
    const post = new Request(`${appUrl}/api/auth/oauth2/callback/university_sso`, {
      method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded' }, body: 'state=signed-state&code=auth-code',
    })
    const normalizedPost = normalizeInstitutionalOidcCallback(post, 'university_sso')
    expect(normalizedPost.method).toBe('POST')
    expect(await normalizedPost.text()).toBe('state=signed-state&code=auth-code')
    expect(normalizeInstitutionalOidcCallback(original, undefined)).toBe(original)
    expect(normalizeInstitutionalOidcCallback(original, 'different_provider')).toBe(original)
  })

  it('still requires authentic state when the old callback reaches the new handler', async () => {
    mockDiscovery()
    const auth = createTestAuth()
    const response = await auth.handler(normalizeInstitutionalOidcCallback(
      new Request(`${appUrl}/api/auth/oauth2/callback/university_sso?state=forged&code=forged`),
      'university_sso',
    ))
    expect(response.status).toBe(302)
    expect(response.headers.get('location')).toContain('error=state_mismatch')
    expect(response.headers.get('set-cookie') || '').not.toContain('session_token')
  })

  it.each(['google', 'github', 'credential'])('rejects the reserved OIDC provider ID %s', (providerId) => {
    expect(() => readOidcConfig({
      OIDC_PROVIDER_ID: providerId,
      OIDC_DISCOVERY_URL: discoveryUrl,
      OIDC_CLIENT_ID: 'test-client', OIDC_CLIENT_SECRET: 'test-secret',
    })).toThrow(/must not shadow/)
  })
})
