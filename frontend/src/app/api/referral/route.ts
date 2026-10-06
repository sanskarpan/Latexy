import { NextRequest, NextResponse } from 'next/server'

import { BACKEND_URL, authHeaders, forwardError } from '@/app/api/byok/_forward'

export const dynamic = 'force-dynamic'

export async function GET(request: NextRequest) {
  const response = await fetch(`${BACKEND_URL}/referral/status`, {
    headers: authHeaders(request),
    cache: 'no-store',
  })
  if (!response.ok) return forwardError(response, 'Referral status')
  return NextResponse.json(await response.json())
}

export async function POST(request: NextRequest) {
  let code = request.cookies.get('latexy_referral')?.value || ''
  try {
    const body = await request.json() as { code?: unknown }
    if (typeof body.code === 'string' && body.code) code = body.code
  } catch {
    // The first-party referral cookie is the normal capture path.
  }
  const response = await fetch(`${BACKEND_URL}/referral/claim`, {
    method: 'POST',
    headers: authHeaders(request),
    body: JSON.stringify({ code }),
    cache: 'no-store',
  })
  const result = response.ok ? NextResponse.json(await response.json()) : await forwardError(response, 'Referral claim')
  if (response.ok) {
    // Attribution is first-touch. Remove the browser token after the server
    // has accepted/rejected it so it cannot linger in unrelated requests.
    result.cookies.set('latexy_referral', '', { maxAge: 0, path: '/' })
  }
  return result
}
