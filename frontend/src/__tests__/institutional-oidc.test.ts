import { describe, expect, it } from 'vitest'
import { readAdditionalTrustedOrigins, readOidcConfig } from '@/lib/oidc-config'

describe('institutional OIDC configuration', () => {
  it('is disabled when no provider values are supplied', () => {
    expect(readOidcConfig({})).toBeNull()
  })

  it('builds a PKCE-enabled OpenID Connect provider without exposing its secret', () => {
    const config = readOidcConfig({
      OIDC_PROVIDER_ID: 'university_sso',
      OIDC_PROVIDER_LABEL: 'Example University',
      OIDC_DISCOVERY_URL: 'https://id.example.edu/.well-known/openid-configuration',
      OIDC_CLIENT_ID: 'latexy',
      OIDC_CLIENT_SECRET: 'server-secret',
    })

    expect(config?.provider).toMatchObject({
      providerId: 'university_sso',
      pkce: true,
      scopes: ['openid', 'profile', 'email'],
    })
    expect(config?.public).toEqual({ id: 'university_sso', label: 'Example University' })
    expect(JSON.stringify(config?.public)).not.toContain('server-secret')
  })

  it('fails closed for partial or insecure remote configuration', () => {
    expect(() => readOidcConfig({ OIDC_PROVIDER_ID: 'school' })).toThrow(/configured together/)
    expect(() => readOidcConfig({
      OIDC_PROVIDER_ID: 'school',
      OIDC_DISCOVERY_URL: 'http://id.example.edu/.well-known/openid-configuration',
      OIDC_CLIENT_ID: 'latexy',
      OIDC_CLIENT_SECRET: 'secret',
    })).toThrow(/HTTPS/)
  })

  it('allows HTTP only for a local development identity provider', () => {
    expect(readOidcConfig({
      OIDC_PROVIDER_ID: 'local_keycloak',
      OIDC_DISCOVERY_URL: 'http://localhost:8080/realms/latexy/.well-known/openid-configuration',
      OIDC_CLIENT_ID: 'latexy',
      OIDC_CLIENT_SECRET: 'secret',
    })?.provider.discoveryUrl).toContain('localhost:8080')
  })

  it('accepts only explicit bare HTTPS trusted origins', () => {
    expect(readAdditionalTrustedOrigins({
      BETTER_AUTH_TRUSTED_ORIGINS: 'https://cv.example.edu, http://localhost:5180',
    })).toEqual(['https://cv.example.edu', 'http://localhost:5180'])
    expect(() => readAdditionalTrustedOrigins({
      BETTER_AUTH_TRUSTED_ORIGINS: 'https://*.example.edu',
    })).toThrow()
    expect(() => readAdditionalTrustedOrigins({
      BETTER_AUTH_TRUSTED_ORIGINS: 'https://cv.example.edu/path',
    })).toThrow(/bare/)
  })
})
