import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL, authHeaders } from '@/app/api/byok/_forward'

export const dynamic = 'force-dynamic'

/** Same-origin, read-only bridge for the extension's existing narrow host scope.
 * Never expose a token or rely on extension-local cached plan permissions.
 */
export async function GET(request: NextRequest) {
  try {
    const options = { headers: authHeaders(request), cache: 'no-store' as const, signal: AbortSignal.timeout(8000) }
    const account = await fetch(`${BACKEND_URL}/me`, options)
    if (!account.ok) return NextResponse.json({ available: false }, { status: account.status, headers: { 'Cache-Control': 'no-store' } })
    const response = await fetch(`${BACKEND_URL}/config/entitlements`, options)
    if (!response.ok) return NextResponse.json({ available: false }, { status: response.status, headers: { 'Cache-Control': 'no-store' } })
    const data = await response.json()
    return NextResponse.json({ available: data?.features?.e13 === true }, { headers: { 'Cache-Control': 'no-store' } })
  } catch {
    return NextResponse.json({ available: false }, { status: 503, headers: { 'Cache-Control': 'no-store' } })
  }
}
