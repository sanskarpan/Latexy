/**
 * Privacy-first PostHog boundary.
 *
 * This is the ONLY module allowed to import `posthog-js` or call `posthog.init`.
 * The CI privacy guard enforces that rule so a future feature cannot bypass the
 * consent gate, text masking, or document-surface blocking implemented here.
 *
 * Policy:
 *  - Nothing loads, captures, or records until the visitor grants analytics
 *    consent. The banner in `AnalyticsConsentBanner` writes that choice.
 *  - Session replay masks every text node and every input by default.
 *  - Document-editing, share, and portfolio surfaces are explicitly blocked
 *    with `ph-no-capture` / `[data-ph-no-capture]`.
 *  - No email, name, résumé content, LaTeX source, prompt, token, or secret is
 *    sent as an event property. IDs and low-cardinality enums only.
 */

import {
  replayTriageLinks,
  type ReplayLinkConfig,
  type ReplayTriageLinks,
} from './replay-links'

export const ANALYTICS_CONSENT_KEY = 'latexy-analytics-consent'
export const ANALYTICS_CONSENT_EVENT = 'latexy:analytics-consent'

export type AnalyticsConsent = 'granted' | 'denied' | null
export type AnalyticsProperties = Record<string, string | number | boolean | null | undefined>

// Keep direct `process.env.NEXT_PUBLIC_*` member expressions so Next inlines
// them at build time, while remaining safe in browser-only bundles (for
// example the esbuild hydration fixture) where `process` is undefined.
const POSTHOG_KEY = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_KEY)?.trim() || ''
const POSTHOG_HOST = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_HOST)?.trim() || 'https://us.i.posthog.com'
const POSTHOG_UI_HOST = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_UI_HOST)?.trim() || 'https://us.posthog.com'
const POSTHOG_PROJECT_ID = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_PROJECT_ID)?.trim() || ''

// Keys that may contain personal or document content. These are dropped even
// when a caller accidentally passes them. A small allowlist keeps genuinely
// useful low-cardinality fields (for example `feature_key`) addressable.
const SENSITIVE_KEY = /(email|phone|name|address|resume|latex|content|prompt|text|token|secret|password|auth|cookie|ssn|birth|salary|job.?description|cover.?letter)/i
const SAFE_KEY_ALLOWLIST = new Set(['feature_key', 'plan_key', 'event_type', 'surface', 'route'])
const MAX_PROPERTIES = 25
const MAX_STRING_LENGTH = 200

type PostHogClient = typeof import('posthog-js').default

let client: PostHogClient | null = null
let initPromise: Promise<boolean> | null = null

export function isAnalyticsConfigured(): boolean {
  return Boolean(POSTHOG_KEY)
}

export function readAnalyticsConsent(): AnalyticsConsent {
  if (typeof window === 'undefined') return null
  try {
    const value = window.localStorage.getItem(ANALYTICS_CONSENT_KEY)
    return value === 'granted' || value === 'denied' ? value : null
  } catch {
    return null
  }
}

export function writeAnalyticsConsent(consent: AnalyticsConsent): void {
  if (typeof window === 'undefined') return
  try {
    if (consent === null) window.localStorage.removeItem(ANALYTICS_CONSENT_KEY)
    else window.localStorage.setItem(ANALYTICS_CONSENT_KEY, consent)
  } catch {
    // Storage can be unavailable in private browsing. The in-memory choice
    // still controls this page; the banner simply reappears next visit.
  }
  window.dispatchEvent(new CustomEvent<AnalyticsConsent>(ANALYTICS_CONSENT_EVENT, { detail: consent }))
}

/** Remove query strings and opaque path identifiers before a URL reaches PostHog. */
export function sanitizeAnalyticsPath(pathname: string): string {
  const clean = pathname.split('?')[0].split('#')[0] || '/'
  return clean
    .replace(/\/r\/[^/]+/g, '/r/:token')
    .replace(/\/u\/[^/]+/g, '/u/:username')
    .replace(/\/share\/[^/]+/g, '/share/:token')
    .replace(/\/portfolio\/[^/]+/g, '/portfolio/:username')
    .replace(/\/workspace\/[^/]+/g, '/workspace/:resumeId')
    .replace(/\/workspaces\/[^/]+/g, '/workspaces/:workspaceId')
    .slice(0, 240)
}

export function sanitizeAnalyticsProperties(properties?: Record<string, unknown>): AnalyticsProperties {
  if (!properties) return {}
  const safe: AnalyticsProperties = {}
  let count = 0
  for (const [rawKey, value] of Object.entries(properties)) {
    if (count >= MAX_PROPERTIES) break
    const key = rawKey.slice(0, 80)
    if (SENSITIVE_KEY.test(key) && !SAFE_KEY_ALLOWLIST.has(key)) continue
    if (value === null || typeof value === 'boolean') {
      safe[key] = value
    } else if (typeof value === 'number') {
      if (Number.isFinite(value)) safe[key] = value
    } else if (typeof value === 'string') {
      safe[key] = value.slice(0, MAX_STRING_LENGTH)
    }
    count += 1
  }
  return safe
}

function sanitizeUrl(value: string): string {
  try {
    const url = new URL(value, typeof window === 'undefined' ? undefined : window.location.origin)
    return `${url.origin}${sanitizeAnalyticsPath(url.pathname)}`
  } catch {
    return ''
  }
}

function safeReferrer(): string | undefined {
  if (typeof document === 'undefined' || !document.referrer) return undefined
  return sanitizeUrl(document.referrer)
}

async function loadClient(): Promise<PostHogClient | null> {
  if (!isAnalyticsConfigured() || typeof window === 'undefined') return null
  if (client) return client
  if (initPromise) return (await initPromise) ? client : null

  initPromise = (async () => {
    try {
      const { default: posthog } = await import('posthog-js')
      posthog.init(POSTHOG_KEY, {
        api_host: POSTHOG_HOST,
        ui_host: POSTHOG_UI_HOST,
        // Pageviews are captured by AnalyticsProvider after the route settles,
        // which lets us strip opaque path tokens first. Pageleave is disabled
        // because the SDK builds it from window.location.href, which can carry
        // a share token on public document routes.
        capture_pageview: false,
        capture_pageleave: false,
        person_profiles: 'identified_only',
        // Applies to every SDK-created event, including autocapture and
        // exceptions, not just the wrapper's explicit captures.
        before_send: (event) => {
          const properties = event.properties ?? {}
          if (typeof properties.$current_url === 'string') {
            properties.$current_url = sanitizeUrl(properties.$current_url)
          }
          if (typeof properties.$referrer === 'string') {
            properties.$referrer = sanitizeUrl(properties.$referrer)
          }
          for (const key of Object.keys(properties)) {
            if (key.startsWith('$input') || key === '$selected_content') delete properties[key]
          }
          return event
        },
        persistence: 'localStorage+cookie',
        // Never record until the explicit consent path below starts it.
        disable_session_recording: true,
        // Global masking on top of the project-level "Total privacy" setting.
        mask_all_text: true,
        mask_all_element_attributes: true,
        autocapture: true,
        session_recording: {
          maskAllInputs: true,
          maskTextSelector: '*',
          // In this SDK generation the top-level attribute flag is an
          // autocapture setting; replay reads this object instead.
          maskAllElementAttributes: true,
          blockSelector: '.ph-no-capture, [data-ph-no-capture]',
          recordCrossOriginIframes: false,
          collectFonts: false,
        },
        loaded: (ph) => {
          // Defense in depth: only start if consent is still granted at load.
          if (readAnalyticsConsent() === 'granted') {
            ph.startSessionRecording()
          } else {
            ph.stopSessionRecording()
            ph.opt_out_capturing()
          }
        },
      })
      client = posthog
      return true
    } catch {
      initPromise = null
      return false
    }
  })()

  return (await initPromise) ? client : null
}

/** Initialize PostHog if the visitor granted consent. Safe to call repeatedly. */
export async function initializeAnalytics(): Promise<boolean> {
  if (readAnalyticsConsent() !== 'granted') return false
  const loaded = await loadClient()
  // Consent can be withdrawn while the SDK import is in flight. Re-check after
  // the await so a pending activation cannot undo disableAnalytics().
  if (!loaded || readAnalyticsConsent() !== 'granted') return false
  loaded.opt_in_capturing()
  loaded.startSessionRecording()
  return true
}

/** Stop capture and replay immediately. Used when consent is withdrawn. */
export function disableAnalytics(): void {
  if (!client) return
  try {
    client.stopSessionRecording()
    client.opt_out_capturing()
    client.reset()
  } catch {
    // The SDK is best-effort; never break the page when it is unavailable.
  }
}

export function captureAnalyticsEvent(event: string, properties?: AnalyticsProperties): void {
  if (!client || readAnalyticsConsent() !== 'granted') return
  try {
    client.capture(event, sanitizeAnalyticsProperties(properties))
  } catch {
    // Analytics must never break a product flow.
  }
}

export function capturePageview(pathname: string): void {
  if (!client || readAnalyticsConsent() !== 'granted' || typeof window === 'undefined') return
  const path = sanitizeAnalyticsPath(pathname)
  try {
    client.capture('$pageview', {
      $current_url: `${window.location.origin}${path}`,
      $referrer: safeReferrer(),
      path,
    })
  } catch {
    // Best effort.
  }
}

export function identifyAnalyticsUser(user: {
  id: string
  plan?: string | null
  role?: string | null
  createdAt?: string | Date | null
}): void {
  if (!client || readAnalyticsConsent() !== 'granted' || !user.id) return
  try {
    const createdAt = user.createdAt instanceof Date
      ? user.createdAt.toISOString()
      : user.createdAt ?? undefined
    client.identify(user.id, sanitizeAnalyticsProperties({
      plan: user.plan ?? 'unknown',
      role: user.role ?? 'user',
      account_created_at: createdAt,
    }))
  } catch {
    // Best effort.
  }
}

export function resetAnalyticsUser(): void {
  if (!client) return
  try {
    client.reset()
  } catch {
    // Best effort.
  }
}

export function analyticsDashboardLinks(): {
  replays: string
  dashboards: string
  people: string
  settings: string
} | null {
  if (!POSTHOG_PROJECT_ID) return null
  const base = `${POSTHOG_UI_HOST.replace(/\/$/, '')}/project/${POSTHOG_PROJECT_ID}`
  return {
    replays: `${base}/replay/home`,
    dashboards: `${base}/dashboard`,
    people: `${base}/persons`,
    settings: `${base}/settings/project-replay`,
  }
}

/**
 * Project/date-range configuration for admin replay deep links. The project id
 * is public (it is not the write token) and no per-user value is included.
 * Returns null when PostHog is not configured, matching
 * `analyticsDashboardLinks`.
 */
export function analyticsReplayLinkConfig(days: number): ReplayLinkConfig | null {
  if (!POSTHOG_PROJECT_ID) return null
  return {
    projectId: POSTHOG_PROJECT_ID,
    uiHost: POSTHOG_UI_HOST,
    days,
  }
}

/**
 * Pre-filtered replay triage links for the admin Analytics tab. The filter
 * values are low-cardinality enums and templated route paths, so no token or
 * personal data can leak into a URL. Returns null when PostHog is not
 * configured for deep links.
 */
export function analyticsReplayTriageLinks(days: number): ReplayTriageLinks | null {
  const config = analyticsReplayLinkConfig(days)
  return config ? replayTriageLinks(config) : null
}
