/**
 * Server-side social-provider configuration shared by Better Auth and the
 * public provider-capability endpoint.  Keep credentials out of anything
 * returned to the browser; the endpoint only uses the boolean projection.
 */

export type SocialProviderId = 'google' | 'github'

export type SocialProviderAvailability = Record<SocialProviderId, boolean>

function configured(value: string | undefined): boolean {
  return Boolean(value?.trim())
}

export function getSocialProviderAvailability(): SocialProviderAvailability {
  return {
    google: configured(process.env.GOOGLE_CLIENT_ID) && configured(process.env.GOOGLE_CLIENT_SECRET),
    github: configured(process.env.GITHUB_CLIENT_ID) && configured(process.env.GITHUB_CLIENT_SECRET),
  }
}

export function getConfiguredSocialProviders() {
  const providers: Partial<Record<SocialProviderId, { clientId: string; clientSecret: string }>> = {}
  const availability = getSocialProviderAvailability()

  if (availability.google) {
    providers.google = {
      clientId: process.env.GOOGLE_CLIENT_ID!.trim(),
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!.trim(),
    }
  }
  if (availability.github) {
    providers.github = {
      clientId: process.env.GITHUB_CLIENT_ID!.trim(),
      clientSecret: process.env.GITHUB_CLIENT_SECRET!.trim(),
    }
  }

  return providers
}
