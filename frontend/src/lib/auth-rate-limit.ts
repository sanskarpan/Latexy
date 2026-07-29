/**
 * Shared, atomic per-IP rate limiting for the Better Auth endpoints.
 *
 * Why this exists instead of Better Auth's own limiter:
 *
 * 1. `storage: 'memory'` keeps counters in a per-process Map, so on a
 *    multi-instance / serverless deployment the limit is silently divided by
 *    the instance count.
 * 2. Better Auth's storage interface cannot be made safe under concurrency:
 *    it *reads* the counter in `onRequestRateLimit` and only *writes* it back
 *    in `onResponseRateLimit`, so N concurrent requests all read the same
 *    pre-burst count and all pass the check. Any `customStorage` doing a
 *    read-modify-write also loses updates. A 60-way concurrent burst against
 *    /request-password-reset therefore delivered 60 emails and left the
 *    counter at 1.
 *
 * So the gate runs *in front of* `auth.handler` (see app/api/auth/[...all])
 * and does check-and-increment in a single atomic statement — one
 * `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`, which Postgres serialises
 * per row. The post-increment count is what we compare against the limit, so
 * concurrency cannot let more than `max` requests through a window.
 *
 * Failure mode is deliberately open: if the counter store is unavailable we
 * log and let the request through. Rate limiting is a mitigation, not an
 * authentication control — a DB blip must not 500 sign-in, sign-out and
 * get-session (Better Auth's own database storage wrapper swallows errors for
 * exactly this reason).
 *
 * The `auth_rate_limit` table is created by Alembic migration 0036; this
 * module never issues DDL on the request path.
 *
 * Buckets are keyed on the caller's IP, which is only readable from forwarding
 * headers — so those are honoured only behind a trusted proxy and only from
 * the hop the proxy itself wrote. See `clientIp` below; a limiter that trusts
 * a client-supplied `X-Forwarded-For` is not a limiter at all.
 *
 * Server-only — never import from a Client Component.
 */

import { Pool } from 'pg'

const RATE_LIMIT_TABLE = 'auth_rate_limit'

export interface RateLimitRule {
  /** Window length in seconds. */
  window: number
  /** Max requests per window, per IP, per path. */
  max: number
}

/** Applies to every auth path without a more specific rule below. */
export const DEFAULT_RULE: RateLimitRule = { window: 60, max: 20 }

/**
 * Path-specific rules. The first matching prefix wins.
 *
 * The endpoints that put mail in someone else's inbox get a much tighter
 * budget than the generic one: five per hour per IP is far more than a real
 * user needs and takes the mail-bomb vector off the table. The credential
 * endpoints mirror Better Auth's own built-in defaults (10s / 3).
 */
export const RATE_LIMIT_RULES: ReadonlyArray<{ prefix: string; rule: RateLimitRule }> = [
  { prefix: '/request-password-reset', rule: { window: 3600, max: 5 } },
  { prefix: '/forget-password', rule: { window: 3600, max: 5 } },
  { prefix: '/send-verification-email', rule: { window: 3600, max: 5 } },
  { prefix: '/email-otp/send-verification-otp', rule: { window: 3600, max: 5 } },
  { prefix: '/email-otp/request-password-reset', rule: { window: 3600, max: 5 } },
  { prefix: '/sign-in', rule: { window: 10, max: 3 } },
  { prefix: '/sign-up', rule: { window: 10, max: 3 } },
  { prefix: '/change-password', rule: { window: 10, max: 3 } },
  { prefix: '/change-email', rule: { window: 10, max: 3 } },
]

/** Resolve the rule for a normalised auth path (e.g. "/sign-in/email"). */
export function resolveRule(path: string): RateLimitRule {
  for (const { prefix, rule } of RATE_LIMIT_RULES) {
    if (path === prefix || path.startsWith(`${prefix}/`)) return rule
  }
  return DEFAULT_RULE
}

/**
 * The auth path a request targets, relative to the Better Auth base path
 * ("/api/auth"). Returns "/" for the base path itself.
 */
export function authPathFromUrl(url: string, basePath = '/api/auth'): string {
  const { pathname } = new URL(url)
  const rest = pathname.startsWith(basePath) ? pathname.slice(basePath.length) : pathname
  const trimmed = rest.replace(/\/+$/, '')
  return trimmed || '/'
}

/**
 * True when a trusted reverse proxy terminates client connections in front of
 * this process, so its forwarding headers may be believed. Shipped as `true`
 * in every manifest that puts the bundled nginx in front of us; mirrors the
 * backend's `TRUST_PROXY_HEADERS` setting.
 */
function trustProxyHeaders(): boolean {
  return (process.env.TRUST_PROXY_HEADERS || '').trim().toLowerCase() === 'true'
}

/**
 * Client IP bucket key.
 *
 * Proxy headers are only honoured behind a trusted proxy; otherwise any caller
 * could rotate `X-Forwarded-For` and mint a fresh five-per-hour budget per
 * request, which is precisely the mail-bomb vector this module exists to close.
 *
 * When trusted, prefer `X-Real-IP`: nginx sets it from `$remote_addr`, which
 * fully OVERWRITES whatever the client sent. `X-Forwarded-For` is built with
 * `$proxy_add_x_forwarded_for`, i.e. the client's own value with the real peer
 * APPENDED — so the trustworthy hop is the LAST one, never `split(',')[0]`.
 *
 * Untrusted requests that nonetheless carry an `X-Forwarded-For` share one
 * bucket: Node's request object gives a route handler no peer address, so
 * there is nothing else left to key on, and a shared bucket is the safe
 * direction. Falling back to a single bucket rather than skipping the limit is
 * deliberate — an unknown IP is exactly what an attacker would engineer.
 */
export function clientIp(headers: Headers): string {
  const forwarded = headers.get('x-forwarded-for')
  if (trustProxyHeaders()) {
    const realIp = headers.get('x-real-ip')?.trim()
    if (realIp) return realIp
    if (forwarded) {
      const last = forwarded.split(',').pop()?.trim()
      if (last) return last
    }
  } else if (forwarded) {
    return 'untrusted-proxy'
  }
  return 'unknown'
}

/**
 * Atomically bump the fixed-window counter for `key` and report the result.
 *
 * `last_request` is the window *start*, not the last hit, so a client cannot
 * keep a window alive by hammering it; the window expires a fixed `window`
 * seconds after the first request in it.
 */
export async function consume(
  pool: Pool,
  key: string,
  rule: RateLimitRule,
  now: number = Date.now(),
): Promise<{ count: number; windowStart: number }> {
  const windowMs = rule.window * 1000
  const { rows } = await pool.query<{ count: number; last_request: string }>(
    `INSERT INTO ${RATE_LIMIT_TABLE} (key, count, last_request)
     VALUES ($1, 1, $2)
     ON CONFLICT (key) DO UPDATE SET
       count = CASE WHEN $2 - ${RATE_LIMIT_TABLE}.last_request >= $3
                    THEN 1 ELSE ${RATE_LIMIT_TABLE}.count + 1 END,
       last_request = CASE WHEN $2 - ${RATE_LIMIT_TABLE}.last_request >= $3
                    THEN $2 ELSE ${RATE_LIMIT_TABLE}.last_request END
     RETURNING count, last_request`,
    [key, now, windowMs],
  )
  return { count: rows[0].count, windowStart: Number(rows[0].last_request) }
}

/** Counters are meaningless once their window has long passed; drop rows that
 *  have not been touched in a day so the table cannot grow without bound. */
const RETENTION_MS = 24 * 60 * 60 * 1000
const PRUNE_INTERVAL_MS = 60 * 60 * 1000

let lastPrune = 0

function maybePrune(pool: Pool, now: number): void {
  if (now - lastPrune < PRUNE_INTERVAL_MS) return
  lastPrune = now
  // Fire-and-forget: housekeeping must never delay or fail a request.
  pool
    .query(`DELETE FROM ${RATE_LIMIT_TABLE} WHERE last_request < $1`, [now - RETENTION_MS])
    .catch((err) => console.error('[auth] rate-limit prune failed', err))
}

function tooManyRequests(retryAfterSeconds: number): Response {
  const retryAfter = Math.max(1, retryAfterSeconds)
  return new Response(
    JSON.stringify({ message: 'Too many requests. Please try again later.' }),
    {
      status: 429,
      statusText: 'Too Many Requests',
      headers: {
        'Content-Type': 'application/json',
        'X-Retry-After': String(retryAfter),
        'Retry-After': String(retryAfter),
      },
    },
  )
}

/**
 * Gate one auth request. Returns a 429 Response when the caller is over
 * budget, or `null` to let the request proceed (including when the counter
 * store is unavailable — see the fail-open note at the top of this file).
 */
export async function enforceAuthRateLimit(
  pool: Pool,
  request: Request,
): Promise<Response | null> {
  const path = authPathFromUrl(request.url)
  const rule = resolveRule(path)
  const key = `${clientIp(request.headers)}|${path}`
  const now = Date.now()

  try {
    const { count, windowStart } = await consume(pool, key, rule, now)
    maybePrune(pool, now)
    if (count > rule.max) {
      return tooManyRequests(Math.ceil((windowStart + rule.window * 1000 - now) / 1000))
    }
    return null
  } catch (err) {
    console.error('[auth] rate-limit store unavailable, allowing request', err)
    return null
  }
}
