import type { GenericOAuthConfig } from 'better-auth/plugins'

export interface PublicOidcProvider {
  id: string
  label: string
}

export interface OidcProviderConfiguration {
  provider: GenericOAuthConfig
  public: PublicOidcProvider
}

const PROVIDER_ID_RE = /^[a-z0-9][a-z0-9_-]{1,39}$/

/** Parse one operator-configured institutional OIDC provider at process start. */
export function readOidcConfig(
  env: Record<string, string | undefined> = process.env,
): OidcProviderConfiguration | null {
  const providerId = env.OIDC_PROVIDER_ID?.trim().toLowerCase()
  const discoveryUrl = env.OIDC_DISCOVERY_URL?.trim()
  const clientId = env.OIDC_CLIENT_ID?.trim()
  const clientSecret = env.OIDC_CLIENT_SECRET?.trim()
  const supplied = [providerId, discoveryUrl, clientId, clientSecret].filter(Boolean).length
  if (supplied === 0) return null
  if (supplied !== 4) {
    throw new Error(
      'OIDC_PROVIDER_ID, OIDC_DISCOVERY_URL, OIDC_CLIENT_ID, and OIDC_CLIENT_SECRET must be configured together.',
    )
  }
  if (!PROVIDER_ID_RE.test(providerId!)) {
    throw new Error('OIDC_PROVIDER_ID must contain 2–40 lowercase letters, digits, underscores, or hyphens.')
  }
  const discovery = new URL(discoveryUrl!)
  const localDevelopment =
    discovery.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(discovery.hostname)
  if (discovery.protocol !== 'https:' && !localDevelopment) {
    throw new Error('OIDC_DISCOVERY_URL must use HTTPS (except localhost development).')
  }

  return {
    provider: {
      providerId: providerId!,
      discoveryUrl: discovery.href,
      clientId: clientId!,
      clientSecret: clientSecret!,
      scopes: ['openid', 'profile', 'email'],
      pkce: true,
    },
    public: {
      id: providerId!,
      label: env.OIDC_PROVIDER_LABEL?.trim().slice(0, 80) || 'Organization SSO',
    },
  }
}

export function readAdditionalTrustedOrigins(
  env: Record<string, string | undefined> = process.env,
): string[] {
  const raw = env.BETTER_AUTH_TRUSTED_ORIGINS
  if (!raw) return []
  return raw.split(',').map((entry) => entry.trim()).filter(Boolean).map((entry) => {
    const url = new URL(entry)
    if (
      url.pathname !== '/'
      || url.search
      || url.hash
      || url.username
      || url.password
      || url.hostname.includes('*')
      || !['https:', 'http:'].includes(url.protocol)
    ) {
      throw new Error('BETTER_AUTH_TRUSTED_ORIGINS entries must be bare HTTP(S) origins.')
    }
    if (url.protocol === 'http:' && !['localhost', '127.0.0.1'].includes(url.hostname)) {
      throw new Error('Non-local BETTER_AUTH_TRUSTED_ORIGINS entries must use HTTPS.')
    }
    return url.origin
  })
}

export const oidcConfiguration = readOidcConfig()
