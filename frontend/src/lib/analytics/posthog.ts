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
  recordConsentDecision,
  resolveConsentDecision,
  type ConsentDecision,
  type ConsentSurface,
} from './consent'
import {
  replayTriageLinks,
  type ReplayLinkConfig,
  type ReplayTriageLinks,
} from './replay-links'
import type { SavedInsightLinkConfig } from './saved-insights'
import { externalReferrerHost, readUtmParams, sanitizeLandingPath, UTM_KEYS, UTM_PATTERN, type UtmKey } from './traffic-source'

export const ANALYTICS_CONSENT_KEY = 'latexy-analytics-consent'
export const ANALYTICS_CONSENT_EVENT = 'latexy:analytics-consent'

export type AnalyticsConsent = 'granted' | 'denied' | null
export type AnalyticsProperties = Record<string, string | number | boolean | null | undefined>
export type AnalyticsEventLike = {
  event?: string
  properties?: Record<string, unknown>
}

// Keep direct `process.env.NEXT_PUBLIC_*` member expressions so Next inlines
// them at build time, while remaining safe in browser-only bundles (for
// example the esbuild hydration fixture) where `process` is undefined.
const POSTHOG_KEY = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_KEY)?.trim() || ''
const POSTHOG_HOST = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_HOST)?.trim() || 'https://us.i.posthog.com'
const POSTHOG_UI_HOST = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_UI_HOST)?.trim() || 'https://us.posthog.com'
const POSTHOG_PROJECT_ID = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_PROJECT_ID)?.trim() || ''

// Optional saved-insight short ids. Each is read directly from a
// `NEXT_PUBLIC_*` member expression so Next can inline it at build time. A
// blank value is valid: the admin catalog then opens a prefilled draft view
// instead of failing.
const POSTHOG_INSIGHT_FUNNEL_ID = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_INSIGHT_FUNNEL_ID)?.trim() || ''
const POSTHOG_INSIGHT_TRENDS_ID = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_INSIGHT_TRENDS_ID)?.trim() || ''
const POSTHOG_INSIGHT_PATHS_ID = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_INSIGHT_PATHS_ID)?.trim() || ''
const POSTHOG_INSIGHT_RETENTION_ID = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_INSIGHT_RETENTION_ID)?.trim() || ''
const POSTHOG_INSIGHT_STICKINESS_ID = (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_POSTHOG_INSIGHT_STICKINESS_ID)?.trim() || ''

// Keys that may contain personal or document content. These are dropped even
// when a caller accidentally passes them. A small allowlist keeps genuinely
// useful low-cardinality fields (for example `feature_key`) addressable.
const SENSITIVE_KEY = /(email|phone|name|address|resume|latex|content|prompt|text|token|secret|password|auth|cookie|ssn|birth|salary|job.?description|cover.?letter)/i

// Document-editing, public share, portfolio, and guest-editor surfaces are
// excluded from *all* browser telemetry, not only session replay. Exception
// autocapture and frustration-signal events would otherwise inspect the same
// pages that hold résumé text, share tokens, or workspace identifiers.
const BLOCKED_ANALYTICS_SURFACE = /^\/(?:workspace|workspaces|try|r|u|share|portfolio)(?:\/|$)/i
const EXCEPTION_TYPE_PATTERN = /^[A-Za-z_$][A-Za-z0-9_$.]{0,63}$/
const EMAIL_PATTERN = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g
const TOKEN_PATTERN = /(?:phc_|phx_|sk-|Bearer\s+)[A-Za-z0-9._~+/=-]{8,}/gi
const URL_PATTERN = /https?:\/\/[^\s"'<>]+/gi
const UUID_PATTERN = /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/gi
const SAFE_KEY_ALLOWLIST = new Set([
  'feature_key',
  'plan_key',
  'event_type',
  'surface',
  'route',
  // Bounded campaign labels. `utm_content` would otherwise match the generic
  // "content" guard even though it never carries document text.
  'utm_source',
  'utm_medium',
  'utm_campaign',
  'utm_content',
  'utm_term',
  'referrer_host',
  'landing_path',
])
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

export function writeAnalyticsConsent(
  consent: AnalyticsConsent,
  surface: ConsentSurface = 'other',
): void {
  if (typeof window === 'undefined') return

  const previous = readAnalyticsConsent()
  // A fresh grant is recorded once. Denying before any grant is a denial;
  // moving away from a prior grant (to denied or to no choice) is a withdrawal
  // and must stop capture/replay immediately.
  const decision: ConsentDecision | null = resolveConsentDecision(previous, consent)

  // Stop the vendor before anything else on withdrawal. This is synchronous
  // and does not wait for the first-party record or a React re-render.
  if (decision === 'withdrawn' || consent === 'denied') disableAnalytics()

  // Record the choice with the first-party backend before PostHog can be
  // initialized. This path is independent of the PostHog SDK and works even
  // when the vendor is blocked.
  if (decision) recordConsentDecision(decision, surface)

  try {
    if (consent === null) window.localStorage.removeItem(ANALYTICS_CONSENT_KEY)
    else window.localStorage.setItem(ANALYTICS_CONSENT_KEY, consent)
  } catch {
    // Storage can be unavailable in private browsing. The in-memory choice
    // still controls this page; the banner simply reappears next visit.
  }
  window.dispatchEvent(new CustomEvent<AnalyticsConsent>(ANALYTICS_CONSENT_EVENT, { detail: consent }))

  if (decision === 'granted') {
    // Consent is already persisted. Only now may the vendor load and start;
    // the grant event itself is never captured before this point.
    void initializeAnalytics().then((ok) => {
      if (!ok) return
      captureAnalyticsEvent('consent_granted', {
        decision: 'granted',
        surface,
      })
    })
  }
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

/**
 * A release tag is a bounded, low-cardinality identifier (git SHA, semver tag,
 * or build id). Anything containing whitespace, a slash, or a free-form value
 * is rejected rather than forwarded to PostHog.
 */
export function sanitizeAnalyticsRelease(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (/^(?:phc_|phx_|sk-|bearer)/i.test(trimmed)) return null
  return /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/.test(trimmed) ? trimmed : null
}

const POSTHOG_RELEASE = sanitizeAnalyticsRelease(
  (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_APP_RELEASE)?.trim() || '',
)

/** The sanitized release tag attached to browser events, when configured. */
export function analyticsRelease(): string | null {
  return POSTHOG_RELEASE
}

function analyticsPathname(value: string): string | null {
  if (!value) return null
  try {
    return new URL(value, 'https://latexy.invalid').pathname || '/'
  } catch {
    return null
  }
}

/**
 * Document, share, portfolio, guest-editor, and workspace paths never reach
 * PostHog. This applies to exception autocapture and dead/rage-click events as
 * well as replay: a stack trace or click on a résumé page is still content.
 */
export function isBlockedAnalyticsPath(value: string): boolean {
  const pathname = analyticsPathname(value)
  return pathname ? BLOCKED_ANALYTICS_SURFACE.test(pathname) : false
}

/** Bound and redact free-form exception text before it reaches PostHog. */
export function sanitizeExceptionText(value: unknown, maxLength = 240): string {
  if (typeof value !== 'string') return ''
  return value
    .replace(URL_PATTERN, (match) => sanitizeUrlLike(match, 160))
    .replace(EMAIL_PATTERN, '[email]')
    .replace(TOKEN_PATTERN, '[token]')
    .replace(UUID_PATTERN, '[id]')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, maxLength)
}

function sanitizeExceptionType(value: unknown): string {
  if (typeof value !== 'string') return 'Error'
  const trimmed = value.trim()
  return EXCEPTION_TYPE_PATTERN.test(trimmed) ? trimmed : 'Error'
}

function sanitizeUrlLike(value: string, maxLength: number): string {
  try {
    const url = new URL(value, 'https://latexy.invalid')
    const keepOrigin =
      url.origin !== 'https://latexy.invalid' &&
      (url.protocol === 'http:' || url.protocol === 'https:')
    const path = `${keepOrigin ? url.origin : ''}${url.pathname}`
    return path.slice(0, maxLength)
  } catch {
    return value.split('?')[0].split('#')[0].slice(0, maxLength)
  }
}

function sanitizeStackFrame(frame: unknown): Record<string, unknown> | null {
  if (!frame || typeof frame !== 'object') return null
  const source = frame as Record<string, unknown>
  const output: Record<string, unknown> = {}
  if (typeof source.filename === 'string') {
    const filename = sanitizeUrlLike(source.filename, 240)
    if (filename) output.filename = filename
  }
  if (typeof source.function === 'string') {
    output.function = sanitizeExceptionText(source.function, 120)
  }
  if (typeof source.module === 'string') {
    output.module = sanitizeExceptionText(source.module, 120)
  }
  if (typeof source.lineno === 'number' && Number.isFinite(source.lineno)) {
    output.lineno = source.lineno
  }
  if (typeof source.colno === 'number' && Number.isFinite(source.colno)) {
    output.colno = source.colno
  }
  if (typeof source.in_app === 'boolean') output.in_app = source.in_app
  return Object.keys(output).length > 0 ? output : null
}

function sanitizeExceptionList(value: unknown): Record<string, unknown>[] | null {
  if (!Array.isArray(value)) return null
  const entries = value
    .slice(0, 5)
    .map((entry): Record<string, unknown> | null => {
      if (!entry || typeof entry !== 'object') return null
      const source = entry as Record<string, unknown>
      const output: Record<string, unknown> = {
        type: sanitizeExceptionType(source.type),
        value: sanitizeExceptionText(source.value),
      }
      if (source.mechanism && typeof source.mechanism === 'object') {
        const mechanism = source.mechanism as Record<string, unknown>
        output.mechanism = {
          ...(typeof mechanism.handled === 'boolean' ? { handled: mechanism.handled } : {}),
          ...(typeof mechanism.type === 'string'
            ? { type: sanitizeExceptionText(mechanism.type, 80) }
            : {}),
        }
      }
      if (source.stacktrace && typeof source.stacktrace === 'object') {
        const stack = source.stacktrace as Record<string, unknown>
        output.stacktrace = {
          ...(stack.type === 'raw' ? { type: 'raw' } : {}),
          ...(Array.isArray(stack.frames)
            ? {
                frames: stack.frames
                  .slice(0, 50)
                  .map(sanitizeStackFrame)
                  .filter((frame): frame is Record<string, unknown> => frame !== null),
              }
            : {}),
        }
      }
      return output
    })
    .filter((entry): entry is Record<string, unknown> => entry !== null)
  return entries.length > 0 ? entries : null
}

function sanitizeExceptionProperties(properties: Record<string, unknown>): void {
  const exceptionList = sanitizeExceptionList(properties.$exception_list)
  if (exceptionList) {
    properties.$exception_list = exceptionList
    properties.error_type = sanitizeExceptionType(exceptionList[0]?.type)
  }
  if (Array.isArray(properties.$exception_types)) {
    properties.$exception_types = properties.$exception_types
      .slice(0, 10)
      .map((value) => sanitizeExceptionType(value))
  }
  if (Array.isArray(properties.$exception_values)) {
    properties.$exception_values = properties.$exception_values
      .slice(0, 10)
      .map((value) => sanitizeExceptionText(value))
  }
  if (typeof properties.$exception_message === 'string') {
    properties.$exception_message = sanitizeExceptionText(properties.$exception_message)
  }
  if (typeof properties.error_type !== 'string') {
    properties.error_type = 'Error'
  }
}

/**
 * The single `before_send` boundary for *all* SDK events, including
 * autocaptured clicks, exceptions, and dead clicks. It removes document
 * surfaces entirely, templates URL paths, attaches the optional release tag,
 * and redacts exception payloads.
 */
export function sanitizeAnalyticsEvent<T extends AnalyticsEventLike>(event: T): T | null {
  const properties = event.properties
  if (!properties) return event

  const currentUrl = typeof properties.$current_url === 'string'
    ? properties.$current_url
    : null
  const pathname = typeof properties.$pathname === 'string'
    ? properties.$pathname
    : null
  const isContentEvent =
    event.event === '$exception' ||
    event.event === '$rageclick' ||
    event.event === '$dead_click' ||
    Array.isArray(properties.$exception_list)
  if (
    isContentEvent &&
    ((currentUrl && isBlockedAnalyticsPath(currentUrl)) ||
      (pathname && isBlockedAnalyticsPath(pathname)))
  ) {
    return null
  }

  if (currentUrl) properties.$current_url = sanitizeUrl(currentUrl)
  if (typeof properties.$referrer === 'string') {
    properties.$referrer = sanitizeUrl(properties.$referrer)
  }
  if (pathname) properties.$pathname = sanitizeAnalyticsPath(pathname)
  if (typeof properties.$session_entry_url === 'string') {
    properties.$session_entry_url = sanitizeUrl(properties.$session_entry_url)
  }

  const route = analyticsPathname(currentUrl ?? pathname ?? '')
  if (route && typeof properties.route !== 'string') {
    properties.route = sanitizeAnalyticsPath(route)
  }

  if (POSTHOG_RELEASE) {
    properties.release = POSTHOG_RELEASE
    if (!properties.$release_id) properties.$release_id = POSTHOG_RELEASE
  }

  for (const key of Object.keys(properties)) {
    if (key.startsWith('$input') || key === '$selected_content' || key === '$exception_steps') {
      delete properties[key]
    }
  }

  // Rage/dead-click autocapture can attach the clicked element's text and DOM
  // chain. The admin triage groups by route/release/event class only, so keep
  // element text out of the event stream entirely.
  if (event.event === '$rageclick' || event.event === '$dead_click') {
    for (const key of ['$el_text', '$elements_chain', '$elements']) {
      delete properties[key]
    }
  }

  if (event.event === '$exception' || Array.isArray(properties.$exception_list)) {
    sanitizeExceptionProperties(properties)
  }
  return event
}

export function sanitizeAnalyticsProperties(properties?: Record<string, unknown>): AnalyticsProperties {
  if (!properties) return {}
  const safe: AnalyticsProperties = {}
  let count = 0
  for (const [rawKey, value] of Object.entries(properties)) {
    if (count >= MAX_PROPERTIES) break
    const key = rawKey.slice(0, 80)
    if (SENSITIVE_KEY.test(key) && !SAFE_KEY_ALLOWLIST.has(key)) continue
    if (UTM_KEYS.includes(key as UtmKey)) {
      if (typeof value !== 'string' || !UTM_PATTERN.test(value)) continue
      safe[key] = value.slice(0, 64).toLowerCase()
      count += 1
      continue
    }
    if (key === 'referrer_host') {
      if (typeof value !== 'string') continue
      const host = externalReferrerHost(`https://${value}`)
      if (!host) continue
      safe[key] = host
      count += 1
      continue
    }
    if (key === 'landing_path') {
      if (typeof value !== 'string' || !value.startsWith('/') || value.includes('://')) continue
      safe[key] = sanitizeLandingPath(value)
      count += 1
      continue
    }
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
    const url = new URL(
      value,
      typeof window === 'undefined' ? 'https://latexy.invalid' : window.location.origin,
    )
    const keepOrigin =
      url.origin !== 'https://latexy.invalid' &&
      (url.protocol === 'http:' || url.protocol === 'https:')
    return `${keepOrigin ? url.origin : ''}${sanitizeAnalyticsPath(url.pathname)}`
  } catch {
    return ''
  }
}

function safeReferrerHost(): string | undefined {
  if (typeof document === 'undefined' || !document.referrer) return undefined
  return externalReferrerHost(document.referrer, window.location.hostname) ?? undefined
}

async function loadClient(): Promise<PostHogClient | null> {
  if (!isAnalyticsConfigured() || typeof window === 'undefined') return null
  if (client) return client
  if (initPromise) return (await initPromise) ? client : null

  initPromise = (async () => {
    try {
      const { default: posthog } = await import('posthog-js')
      if (POSTHOG_RELEASE) {
        // PostHog's exception pipeline reads this when it builds `$release_id`.
        // Setting it before init keeps release-tagged exceptions consistent
        // with the `release` super property registered below.
        const runtimeGlobal = globalThis as typeof globalThis & { _posthogReleaseId?: string }
        runtimeGlobal._posthogReleaseId = POSTHOG_RELEASE
      }
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
        // Exception autocapture is consent-gated like every other event: this
        // init path only runs after a grant. `before_send` drops errors raised
        // on document surfaces and redacts exception payloads.
        capture_exceptions: true,
        // Frustration signals used by the admin Quality view. Rage clicks are
        // part of autocapture; dead clicks need the explicit extension.
        capture_dead_clicks: true,
        rageclick: true,
        // Applies to every SDK-created event, including autocapture, dead
        // clicks, and exceptions, not just the wrapper's explicit captures.
        before_send: (event) => sanitizeAnalyticsEvent(event),
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
            if (POSTHOG_RELEASE) ph.register({ release: POSTHOG_RELEASE })
            ph.startSessionRecording()
            ph.startExceptionAutocapture()
          } else {
            ph.stopSessionRecording()
            ph.stopExceptionAutocapture()
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
  loaded.startExceptionAutocapture()
  if (POSTHOG_RELEASE) loaded.register({ release: POSTHOG_RELEASE })
  return true
}

/** Stop capture and replay immediately. Used when consent is withdrawn. */
export function disableAnalytics(): void {
  if (!client) return
  // Each call is isolated: a failure stopping one extension must not skip the
  // opt-out/reset that makes withdrawal take effect.
  try {
    client.stopSessionRecording()
  } catch {
    // The SDK is best-effort; never break the page when it is unavailable.
  }
  try {
    client.stopExceptionAutocapture()
  } catch {
    // Continue to the opt-out below even if the extension is not loaded.
  }
  try {
    client.opt_out_capturing()
  } catch {
    // The SDK is best-effort.
  }
  try {
    client.reset()
  } catch {
    // The SDK is best-effort.
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

export function capturePageview(
  pathname: string,
  context?: {
    pageKey?: string | null
    experiment?: string | null
    variant?: string | null
    deviceClass?: string | null
  },
): void {
  if (!client || readAnalyticsConsent() !== 'granted' || typeof window === 'undefined') return
  const path = sanitizeAnalyticsPath(pathname)
  const utm = readUtmParams(window.location.search)
  const referrerHost = safeReferrerHost()
  const hasAttribution = Object.keys(utm).length > 0 || Boolean(referrerHost)
  const properties: AnalyticsProperties = {
    // Origin + sanitized path only; UTM values are captured separately below
    // because sanitizeAnalyticsPath deliberately strips the query string.
    $current_url: `${window.location.origin}${path}`,
    // A host is enough for source reporting and cannot carry a query-string
    // token or an arbitrary external path.
    ...(referrerHost ? { $referrer: `https://${referrerHost}` } : {}),
    path,
    ...utm,
    ...(referrerHost ? { referrer_host: referrerHost } : {}),
    ...(hasAttribution ? { landing_path: path } : {}),
  }
  // Landing attribution is low-cardinality only. A missing variant is omitted
  // rather than filled in with an invented control group.
  if (context?.pageKey) properties.page_key = context.pageKey
  if (context?.experiment) properties.experiment = context.experiment
  if (context?.variant) properties.variant = context.variant
  if (context?.deviceClass) properties.device_class = context.deviceClass
  try {
    client.capture('$pageview', properties)
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
 * Project/date-range configuration for the admin Quality triage view. The
 * project id is public and no per-user value is included; the quality view
 * never reads or embeds PostHog data, only opens filtered aggregate views.
 */
export function analyticsQualityLinkConfig(days: number): ReplayLinkConfig | null {
  // Quality counts need both the write token and the project id: without the
  // token this deployment cannot have sent any exception/frustration events.
  if (!isAnalyticsConfigured() || !POSTHOG_PROJECT_ID) return null
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

/**
 * Project/date-range configuration for the admin saved-insight catalog. Only
 * the public project id and optional saved short ids are used; the write token
 * is never read, so the catalog still works when browser capture is blocked or
 * unconfigured. Returns null when the project id is absent, which lets the
 * Analytics tab keep rendering the authoritative first-party KPI cards.
 */
export function analyticsSavedInsightConfig(days: number): SavedInsightLinkConfig | null {
  if (!POSTHOG_PROJECT_ID) return null
  return {
    projectId: POSTHOG_PROJECT_ID,
    uiHost: POSTHOG_UI_HOST,
    days,
    savedInsightIds: {
      funnel: POSTHOG_INSIGHT_FUNNEL_ID,
      trends: POSTHOG_INSIGHT_TRENDS_ID,
      paths: POSTHOG_INSIGHT_PATHS_ID,
      retention: POSTHOG_INSIGHT_RETENTION_ID,
      stickiness: POSTHOG_INSIGHT_STICKINESS_ID,
    },
  }
}
