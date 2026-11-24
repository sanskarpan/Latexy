/**
 * Pure URL builders for pre-filtered PostHog session-replay triage links.
 *
 * This module intentionally has no browser, SDK, or environment access: callers
 * pass the configured project id, UI host, and active date range, so every link
 * can be unit tested and audited. Nothing here ever carries a token, an email,
 * or document content — the filter values are low-cardinality enums and
 * already-templated route paths only.
 *
 * The generated URLs point at the replay home (`/replay/home`) with a `filters`
 * search param whose JSON follows PostHog's universal recording-filters shape
 * (`RecordingUniversalFilters`). PostHog fills any omitted defaults (such as the
 * minimum active-seconds filter and `filter_test_accounts`) on load.
 */

export const DEFAULT_POSTHOG_UI_HOST = 'https://us.posthog.com'

/** Sessions kept only when they contain more active seconds than this. */
export const LONG_SESSION_MIN_ACTIVE_SECONDS = 120

export interface ReplayLinkConfig {
  /** PostHog numeric project id (e.g. `756020`). */
  projectId: string
  /** PostHog app host, without a trailing slash. */
  uiHost?: string
  /** Selected admin date range, in whole days; encoded as a relative `date_from`. */
  days: number
}

export interface ReplayEventFilter {
  id: string
  type: 'events'
  order: number
  name: string
}

export interface ReplayPropertyFilter {
  key: string
  operator: 'exact' | 'icontains'
  type: 'event' | 'person' | 'log_entry'
  value: string | string[]
}

export interface ReplayDurationFilter {
  key: 'active_seconds' | 'duration' | 'inactive_seconds'
  operator: 'gt' | 'lt'
  type: 'recording'
  value: number
}

export interface ReplayUniversalFilter {
  date_from: string
  date_to: null
  duration?: ReplayDurationFilter[]
  filter_group: {
    type: 'AND'
    values: Array<{
      type: 'AND'
      values: Array<ReplayEventFilter | ReplayPropertyFilter>
    }>
  }
}

export interface ReplayTriageLink {
  label: string
  href: string
}

export interface ReplayTriageLinks {
  checkoutFailures: string
  jsErrors: string
  longSessions: string
  routes: ReplayTriageLink[]
  plans: ReplayTriageLink[]
}

/**
 * Routes surfaced for route-specific triage. Paths are the sanitized values the
 * analytics boundary already sends to PostHog (`sanitizeAnalyticsPath`), so a
 * link never exposes a résumé, share, or workspace id. Document, share,
 * portfolio, and guest-editor surfaces are deliberately absent: replay is
 * blocked there, so a triage link would only return an empty list.
 */
export const REPLAY_TRIAGE_ROUTES: ReadonlyArray<{ label: string; path: string }> = [
  { label: 'Dashboard', path: '/dashboard' },
  { label: 'Templates', path: '/templates' },
  { label: 'Tracker', path: '/tracker' },
  { label: 'Billing', path: '/billing' },
  { label: 'Pricing', path: '/pricing' },
  { label: 'Settings', path: '/settings' },
]

/** Plan families surfaced for plan-specific triage, matching the `plan` person property. */
export const REPLAY_TRIAGE_PLANS: ReadonlyArray<{ label: string; key: string }> = [
  { label: 'Free', key: 'free' },
  { label: 'Basic', key: 'basic' },
  { label: 'Pro', key: 'pro' },
  { label: 'BYOK', key: 'byok' },
  { label: 'Team', key: 'team' },
]

function baseFilter(config: ReplayLinkConfig): ReplayUniversalFilter {
  return {
    date_from: `-${config.days}d`,
    date_to: null,
    filter_group: { type: 'AND', values: [{ type: 'AND', values: [] }] },
  }
}

function andGroup(values: Array<ReplayEventFilter | ReplayPropertyFilter>): ReplayUniversalFilter['filter_group'] {
  return { type: 'AND', values: [{ type: 'AND', values }] }
}

/**
 * Build a replay-home URL for the configured project and date range, applying
 * `overrides` on top of the default universal filter and URL-encoding the
 * resulting JSON into the `filters` search param.
 */
export function buildReplayUrl(
  config: ReplayLinkConfig,
  overrides: Partial<ReplayUniversalFilter> = {},
): string {
  const host = (config.uiHost ?? DEFAULT_POSTHOG_UI_HOST).replace(/\/+$/, '')
  const filters: ReplayUniversalFilter = { ...baseFilter(config), ...overrides }
  const encoded = encodeURIComponent(JSON.stringify(filters))
  return `${host}/project/${config.projectId}/replay/home?filters=${encoded}`
}

/** Replays that fired a `checkout_failed` event. */
export function checkoutFailureReplayUrl(config: ReplayLinkConfig): string {
  return buildReplayUrl(config, {
    filter_group: andGroup([{ id: 'checkout_failed', type: 'events', order: 0, name: 'checkout_failed' }]),
  })
}

/** Replays with a browser console error. */
export function jsErrorReplayUrl(config: ReplayLinkConfig): string {
  return buildReplayUrl(config, {
    filter_group: andGroup([{ key: 'level', operator: 'exact', type: 'log_entry', value: ['error'] }]),
  })
}

/** Replays that visited a given (already-sanitized) route path. */
export function routeReplayUrl(config: ReplayLinkConfig, path: string): string {
  return buildReplayUrl(config, {
    filter_group: andGroup([{ key: '$current_url', operator: 'icontains', type: 'event', value: path }]),
  })
}

/** Replays from users on a given plan family, via the `plan` person property. */
export function planReplayUrl(config: ReplayLinkConfig, plan: string): string {
  return buildReplayUrl(config, {
    filter_group: andGroup([{ key: 'plan', operator: 'exact', type: 'person', value: [plan] }]),
  })
}

/** Replays longer than `minActiveSeconds` of active time. */
export function longSessionReplayUrl(
  config: ReplayLinkConfig,
  minActiveSeconds: number = LONG_SESSION_MIN_ACTIVE_SECONDS,
): string {
  return buildReplayUrl(config, {
    duration: [{ key: 'active_seconds', operator: 'gt', type: 'recording', value: minActiveSeconds }],
  })
}

/** Every pre-filtered triage link for the admin Analytics tab. */
export function replayTriageLinks(config: ReplayLinkConfig): ReplayTriageLinks {
  return {
    checkoutFailures: checkoutFailureReplayUrl(config),
    jsErrors: jsErrorReplayUrl(config),
    longSessions: longSessionReplayUrl(config),
    routes: REPLAY_TRIAGE_ROUTES.map((route) => ({
      label: route.label,
      href: routeReplayUrl(config, route.path),
    })),
    plans: REPLAY_TRIAGE_PLANS.map((plan) => ({
      label: plan.label,
      href: planReplayUrl(config, plan.key),
    })),
  }
}
