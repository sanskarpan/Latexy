import { NextResponse } from 'next/server'
import { oidcConfiguration } from '@/lib/oidc-config'
import { getSocialProviderAvailability } from '@/lib/social-provider-config'

export const dynamic = 'force-dynamic'

export function GET() {
  const social = getSocialProviderAvailability()
  return NextResponse.json(
    {
      google: social.google,
      github: social.github,
      oidc: oidcConfiguration?.public ?? null,
    },
    { headers: { 'Cache-Control': 'no-store' } },
  )
}
