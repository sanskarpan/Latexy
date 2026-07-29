import { NextRequest, NextResponse } from 'next/server'

// Backend base URL: prefer the server-only BACKEND_URL, then the public API URL,
// then localhost. Avoids a hardcoded port that breaks non-default deployments.
export const BACKEND_URL =
  process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8030'

// BYOK backend endpoints are per-user and require authentication. This proxy must
// forward the caller's credentials (Bearer token and/or session cookie) so the
// backend can identify the user — without this every BYOK call fails with 401.
export function authHeaders(request: NextRequest): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const auth = request.headers.get('authorization')
  if (auth) headers['Authorization'] = auth
  const cookie = request.headers.get('cookie')
  if (cookie) headers['Cookie'] = cookie
  return headers
}

// Turn a non-OK backend response into a proxy response that keeps the upstream
// status. Laundering a 401/403/404 into a 500 makes an unauthenticated visit look
// like a server fault and prevents callers from reacting appropriately.
export async function forwardError(
  response: Response,
  context: string,
  extra: Record<string, unknown> = {},
): Promise<NextResponse> {
  const raw = await response.text().catch(() => '')
  let detail = raw
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown; error?: unknown }
    const candidate = parsed.detail ?? parsed.error
    if (typeof candidate === 'string') detail = candidate
  } catch {
    // Non-JSON body (HTML error page, empty) — fall back to the raw text.
  }
  console.error(`${context}: backend responded ${response.status}`, detail)
  return NextResponse.json(
    {
      success: false,
      error: detail || `Backend responded with ${response.status}`,
      ...extra,
    },
    { status: response.status },
  )
}
