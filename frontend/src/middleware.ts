import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { negotiateUiLocale } from '@/lib/i18n'

const LATEXY_DOMAINS = new Set([
  'latexy.xyz',
  'www.latexy.xyz',
  'latexy.io',
  'www.latexy.io',
  'localhost',
  '127.0.0.1',
])
const CUSTOM_DOMAIN_TIMEOUT_MS = 2_000

interface TenantHostResponse {
  tenant: { slug: string } | null
}

function configuredAppHostname(): string | null {
  const configured = process.env.NEXT_PUBLIC_APP_URL ?? process.env.BETTER_AUTH_URL
  if (!configured) return null
  try {
    return new URL(configured).hostname
  } catch {
    return null
  }
}

export function shouldBypassPortfolioResolution(hostname: string, pathname: string): boolean {
  const configuredHostname = configuredAppHostname()
  return (
    pathname === '/api' ||
    pathname.startsWith('/api/') ||
    pathname.startsWith('/u/') ||
    LATEXY_DOMAINS.has(hostname) ||
    hostname.endsWith('.vercel.app') ||
    hostname === configuredHostname
  )
}

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
  // UI language is negotiated independently of document translation. Passing
  // it as a request header lets the server layout render the same locale that
  // the client provider receives, avoiding a hydration flash/mismatch.
  const requestHeaders = new Headers(request.headers)
  requestHeaders.set(
    'x-latexy-ui-locale',
    negotiateUiLocale(request.cookies.get('latexy-ui-locale')?.value, request.headers.get('accept-language')),
  )

  // Known Latexy domains, the app's own Vercel deployment domains, and the
  // primary marketing domain → skip (these are NOT custom portfolio domains,
  // so we must not do a per-request resolve-domain lookup or rewrite them).
  if (shouldBypassPortfolioResolution(hostname, request.nextUrl.pathname)) {
    return NextResponse.next({ request: { headers: requestHeaders } })
  }

  // Attempt to resolve domain → username via backend API.
  // This runs on the server, so the base must be absolute: in production
  // NEXT_PUBLIC_API_URL is the same-origin path prefix "/api", which Node's
  // fetch() rejects with "Failed to parse URL". Prefer server-only BACKEND_URL.
  const apiBase =
    process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'
  try {
    // A verified white-label tenant domain serves the full application. Check
    // it before the portfolio resolver so the same hostname can never be
    // misrouted to an unrelated public profile.
    const tenantResponse = await fetch(
      `${apiBase}/tenants/resolve-host?host=${encodeURIComponent(hostname)}`,
      { cache: 'no-store', signal: AbortSignal.timeout(CUSTOM_DOMAIN_TIMEOUT_MS) },
    )
    if (tenantResponse.ok) {
      const { tenant } = await tenantResponse.json() as TenantHostResponse
      if (tenant) {
        requestHeaders.set('x-tenant-slug', tenant.slug)
        const next = NextResponse.next({ request: { headers: requestHeaders } })
        next.cookies.set('latexy_tenant_slug', tenant.slug, {
          maxAge: 60 * 60,
          sameSite: 'lax',
          secure: request.nextUrl.protocol === 'https:',
          path: '/',
        })
        return next
      }
    }

    const res = await fetch(
      `${apiBase}/portfolio/resolve-domain?domain=${encodeURIComponent(hostname)}`,
      { cache: 'no-store', signal: AbortSignal.timeout(CUSTOM_DOMAIN_TIMEOUT_MS) }
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

  return NextResponse.next({ request: { headers: requestHeaders } })
}

export const config = {
  matcher: [
    /*
     * Match all paths except Next.js internals and static files.
     */
    '/((?!api(?:/|$)|_next/static|_next/image|favicon.ico).*)',
  ],
}
