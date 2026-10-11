import { genericOAuth } from 'better-auth/plugins'
import type { OidcProviderConfiguration } from './oidc-config'

/** Keep existing IdP registrations and issuer pins across Better Auth 1.7. */
export function createInstitutionalOidcPlugin(
  configuration: OidcProviderConfiguration,
  appUrl: string,
) {
  const providerId = configuration.provider.providerId
  const plugin = genericOAuth({
    config: [{
      ...configuration.provider,
      // 1.7 handles custom providers through the core social callback. Keep
      // the URI already registered at existing institutions; the outer route
      // aliases only this configured provider into the new core handler.
      redirectURI: `${appUrl.replace(/\/$/, '')}/api/auth/oauth2/callback/${providerId}`,
      requireIdTokenVerification: true,
      // 1.6 signed out of Latexy only. Do not unexpectedly sign users out of
      // their institution or introduce a new post-logout URI registration.
      disableProviderLogout: true,
    }],
  })

  return {
    ...plugin,
    async init(...args: Parameters<typeof plugin.init>) {
      const result = await plugin.init(...args)
      const provider = result.context.socialProviders.find((entry) => entry.id === providerId)
      // Better Auth 1.7 reads issuer from discovery instead of accepting an
      // issuer option. Preserve our operator's optional explicit trust pin.
      if (provider && configuration.expectedIssuer && provider.issuer !== configuration.expectedIssuer) {
        throw new Error('OIDC discovery issuer does not match OIDC_ISSUER.')
      }
      if (provider) {
        const getUserInfo = provider.getUserInfo
        provider.getUserInfo = async (tokens) => {
          // This integration is OIDC, not arbitrary OAuth. Discovery metadata
          // alone must not let a token response omit the signed identity.
          // Preserve redirect-only SSO: the expected nonce comes from signed
          // server-created state, not a client-submitted identity token.
          if (!tokens.idToken || !tokens.expectedIdTokenNonce) return null
          return getUserInfo(tokens)
        }
      }
      return result
    },
  }
}

export function normalizeInstitutionalOidcCallback(
  request: Request,
  providerId: string | undefined,
): Request {
  if (!providerId) return request
  const url = new URL(request.url)
  if (url.pathname !== `/api/auth/oauth2/callback/${providerId}`) return request
  url.pathname = `/api/auth/callback/${providerId}`
  return new Request(url, request)
}
