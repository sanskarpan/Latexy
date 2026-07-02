import { NextRequest } from 'next/server'

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
