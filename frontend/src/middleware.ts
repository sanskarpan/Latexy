import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const LATEXY_DOMAINS = new Set([
  'latexy.io',
  'www.latexy.io',
  'localhost',
  '127.0.0.1',
])

/**
 * Custom domain portfolio routing (Feature 67D).
 *
 * When a request arrives at a domain that is NOT a known Latexy domain,
 * treat it as a custom portfolio domain and rewrite to /u/{username} by
 * looking up the username via the portfolio API.
 *
 * The actual domain → username mapping lives in the database
 * (users.portfolio_custom_domain). We perform a lightweight API call to
 * GET /portfolio/resolve-domain?domain=<host> which returns { username }.
 *
 * On any error or unknown domain the request passes through unchanged.
 */
export async function middleware(request: NextRequest) {
  const host = request.headers.get('host') ?? ''
  // Strip port for local dev
  const hostname = host.replace(/:\d+$/, '')

  // Known Latexy domains → skip
  if (LATEXY_DOMAINS.has(hostname)) {
    return NextResponse.next()
  }

  // Already on a /u/ path — skip to prevent redirect loops
  if (request.nextUrl.pathname.startsWith('/u/')) {
    return NextResponse.next()
  }

  // Attempt to resolve domain → username via backend API
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'
  try {
    const res = await fetch(
      `${apiBase}/portfolio/resolve-domain?domain=${encodeURIComponent(hostname)}`,
      { cache: 'no-store' }
    )
    if (res.ok) {
      const { username } = (await res.json()) as { username: string }
      if (username) {
        const url = request.nextUrl.clone()
        url.pathname = `/u/${username}`
        return NextResponse.rewrite(url)
      }
    }
  } catch {
    // DNS resolution or network error — pass through
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    /*
     * Match all paths except Next.js internals and static files.
     */
    '/((?!_next/static|_next/image|favicon.ico).*)',
  ],
}
