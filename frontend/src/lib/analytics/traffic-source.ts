/**
 * First-party traffic-source capture.
 *
 * UTM parameters exist only in the landing URL's query string, which the
 * general analytics path sanitizer deliberately removes. This module reads the
 * five allowlisted values **before** that sanitization, validates them with a
 * conservative character set, and posts only the allowlisted fields to the
 * first-party API. No raw IP, email, name, token, or full URL is sent.
 *
 * The module is intentionally free of PostHog imports so `posthog.ts` can use
 * the pure helpers without creating an import cycle.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

export const UTM_KEYS = [
  'utm_source',
  'utm_medium',
  'utm_campaign',
  'utm_content',
  'utm_term',
] as const

export type UtmKey = (typeof UTM_KEYS)[number]
export type UtmParams = Partial<Record<UtmKey, string>>

export const UTM_MAX_LENGTH = 64
export const UTM_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._~+-]{0,63}$/

export const TRAFFIC_PENDING_KEY = 'latexy-traffic-attribution-pending'
const TRAFFIC_LANDING_KEY = 'latexy-traffic-landing-captured'
const TRAFFIC_SESSION_KEY = 'latexy-traffic-session-id'

// Capture the landing URL in memory as soon as the client bundle loads. This is
// before any path sanitizer or consent-gated capture runs, so a visitor who
// grants consent after an initial navigation still keeps the original UTM
// values. Nothing is stored or sent until `captureFirstPartyTraffic` is called
// after consent.
const initialLanding =
  typeof window !== 'undefined' && typeof document !== 'undefined'
    ? {
        search: window.location.search,
        pathname: window.location.pathname,
        referrer: document.referrer,
      }
    : null

const OPAQUE_PATH_SEGMENTS: ReadonlyArray<readonly [RegExp, string]> = [
  [/\/workspace\/builder\/[^/]+/g, '/workspace/builder/:resumeId'],
  [/\/workspace\/variant\/[^/]+/g, '/workspace/variant/:resumeId'],
  [/\/r\/[^/]+/g, '/r/:token'],
  [/\/u\/[^/]+/g, '/u/:username'],
  [/\/share\/[^/]+/g, '/share/:token'],
  [/\/portfolio\/[^/]+/g, '/portfolio/:username'],
  [/\/workspace\/(?!builder(?:\/|$)|variant(?:\/|$))[^/]+/g, '/workspace/:resumeId'],
  [/\/workspaces\/[^/]+/g, '/workspaces/:workspaceId'],
]

// Exact static app routes must not be mistaken for a dynamic workspace id.
const STATIC_PATH_EXCEPTIONS = new Set([
  '/workspace/builder/new',
  '/workspace/cover-letters',
  '/workspace/history',
  '/workspace/merge',
  '/workspace/new',
])

const HOST_PATTERN =
  /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/
const IPV4_PATTERN = /^(?:\d{1,3}\.){3}\d{1,3}$/
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

/** Read only allowlisted, bounded UTM values from a query string. */
export function readUtmParams(search: string): UtmParams {
  let params: URLSearchParams
  try {
    params = new URLSearchParams(search)
  } catch {
    return {}
  }
  const safe: UtmParams = {}
  for (const key of UTM_KEYS) {
    const values = params.getAll(key)
    // Duplicate parameters are ambiguous and attacker-controlled; drop them
    // rather than choosing one arbitrarily.
    if (values.length !== 1) continue
    const value = values[0]
    if (typeof value !== 'string' || !UTM_PATTERN.test(value)) continue
    safe[key] = value.toLowerCase()
  }
  return safe
}

/** Return a sanitized pathname; never a full URL or query string. */
export function sanitizeLandingPath(pathname: string): string {
  const clean = (pathname || '/').split('?')[0].split('#')[0] || '/'
  const normalized = clean.length > 1 ? clean.replace(/\/+$/, '') : clean
  if (STATIC_PATH_EXCEPTIONS.has(normalized)) return normalized
  let path = normalized
  for (const [pattern, replacement] of OPAQUE_PATH_SEGMENTS) {
    path = path.replace(pattern, replacement)
  }
  return path.slice(0, 240) || '/'
}

/**
 * Reduce a referrer to an external host only. Same-site referrers, IP hosts,
 * malformed values, and non-HTTP schemes return null.
 */
export function externalReferrerHost(
  referrer: string | null | undefined,
  currentHost?: string,
): string | null {
  if (!referrer) return null
  let parsed: URL
  try {
    parsed = new URL(referrer)
  } catch {
    return null
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null
  const host = parsed.hostname.replace(/\.$/, '').toLowerCase()
  if (!host || host.length > 253) return null
  if (currentHost && host === currentHost.replace(/\.$/, '').toLowerCase()) return null
  if (IPV4_PATTERN.test(host)) return null
  if (host.includes(':')) return null
  return HOST_PATTERN.test(host) ? host : null
}

export interface TrafficLandingPayload {
  landing_path: string
  referrer?: string
  session_id: string
  utm_source?: string
  utm_medium?: string
  utm_campaign?: string
  utm_content?: string
  utm_term?: string
}

export function buildTrafficLandingPayload(input: {
  search: string
  pathname: string
  referrer?: string | null
  currentHost?: string
  sessionId: string
}): TrafficLandingPayload {
  const payload: TrafficLandingPayload = {
    landing_path: sanitizeLandingPath(input.pathname),
    session_id: input.sessionId,
  }
  const referrer = externalReferrerHost(input.referrer, input.currentHost)
  if (referrer) payload.referrer = referrer
  Object.assign(payload, readUtmParams(input.search))
  return payload
}

function randomUuid(): string {
  const cryptoObject = typeof crypto === 'undefined' ? undefined : crypto
  if (cryptoObject?.randomUUID) return cryptoObject.randomUUID()
  const bytes = new Uint8Array(16)
  if (cryptoObject?.getRandomValues) {
    cryptoObject.getRandomValues(bytes)
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256)
    }
  }
  // RFC 4122 version 4 layout.
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function sessionId(): string {
  try {
    const existing = window.sessionStorage.getItem(TRAFFIC_SESSION_KEY)
    if (existing && UUID_PATTERN.test(existing)) return existing
    const created = randomUuid()
    window.sessionStorage.setItem(TRAFFIC_SESSION_KEY, created)
    return created
  } catch {
    return randomUuid()
  }
}

export function hasPendingTrafficAttribution(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(TRAFFIC_PENDING_KEY) === '1'
  } catch {
    return false
  }
}

export function clearPendingTrafficAttribution(): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(TRAFFIC_PENDING_KEY)
  } catch {
    // Storage can be unavailable in private browsing.
  }
}

/**
 * Capture one landing per browser tab/session. This is only called after the
 * visitor grants analytics consent. The payload is built from the raw URL
 * search before any path sanitizer runs.
 */
export function captureFirstPartyTraffic(): void {
  if (typeof window === 'undefined' || typeof document === 'undefined') return
  if (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_PLAYWRIGHT_TEST === '1') return

  try {
    if (window.sessionStorage.getItem(TRAFFIC_LANDING_KEY) === '1') return
    window.sessionStorage.setItem(TRAFFIC_LANDING_KEY, '1')
  } catch {
    // A storage failure should at most duplicate one aggregate landing row.
  }

  const payload = buildTrafficLandingPayload({
    search: initialLanding?.search ?? window.location.search,
    pathname: initialLanding?.pathname ?? window.location.pathname,
    referrer: initialLanding?.referrer ?? document.referrer,
    currentHost: window.location.hostname,
    sessionId: sessionId(),
  })

  try {
    window.localStorage.setItem(TRAFFIC_PENDING_KEY, '1')
  } catch {
    // The claim is best-effort when storage is unavailable.
  }

  void fetch(`${API_BASE}/analytics/traffic/landing`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    credentials: 'include',
    keepalive: true,
  }).catch(() => undefined)
}

/**
 * Claim the server-stored landing for the signed-in account. The browser sends
 * no campaign values; the backend reads its HttpOnly visitor cookie and copies
 * the already-validated first-touch row.
 *
 * A landing capture and a signup can race on a very fast sign-up. ``no_landing``
 * is therefore retried briefly; the pending flag is kept so a later session can
 * try again. Only a definitive result clears it.
 */
export async function claimTrafficAttribution(
  token: string | null | undefined,
): Promise<boolean> {
  if (!token) return false
  if (typeof window === 'undefined') return false
  if (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_PLAYWRIGHT_TEST === '1') return false

  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(`${API_BASE}/analytics/traffic/claim`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        credentials: 'include',
      })
      if (!response.ok) return false
      const result = (await response.json().catch(() => ({}))) as {
        recorded?: boolean
        reason?: string
      }
      if (result.recorded || result.reason === 'already_attributed') {
        clearPendingTrafficAttribution()
        return true
      }
      if (result.reason !== 'no_landing') {
        clearPendingTrafficAttribution()
        return false
      }
    } catch {
      return false
    }
    if (attempt < 2) {
      await new Promise((resolve) => setTimeout(resolve, 800 * (attempt + 1)))
    }
  }
  return false
}
