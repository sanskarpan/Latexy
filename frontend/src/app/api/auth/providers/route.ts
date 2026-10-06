import { NextResponse } from 'next/server'
import { oidcConfiguration } from '@/lib/oidc-config'

export const dynamic = 'force-dynamic'

export function GET() {
  return NextResponse.json(
    { oidc: oidcConfiguration?.public ?? null },
    { headers: { 'Cache-Control': 'public, max-age=300, stale-while-revalidate=3600' } },
  )
}
