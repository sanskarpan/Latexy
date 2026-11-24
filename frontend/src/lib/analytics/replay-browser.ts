/**
 * Pure filter and link contract for the admin session-replay library.
 *
 * PostHog owns the replay data. This module never fetches, embeds, or renders a
 * recording; it only composes the pre-filtered replay-home URLs from
 * `replay-links.ts` for the configured project and selected date range.
 *
 * Filter values are intentionally closed sets: templated product routes, the
 * low-cardinality `plan` person property, one console-error predicate, a bounded
 * duration, and the `checkout_failed` event. Document, share, portfolio, and
 * guest-editor paths are excluded before a URL is built, so they can never be
 * selected or deep-linked from the browser.
 */

import {
  buildReplayUrl,
  LONG_SESSION_MIN_ACTIVE_SECONDS,
  REPLAY_TRIAGE_PLANS,
  REPLAY_TRIAGE_ROUTES,
  type ReplayEventFilter,
  type ReplayLinkConfig,
  type ReplayPropertyFilter,
  type ReplayUniversalFilter,
} from './replay-links'

export type ReplayBrowserErrorKind = 'console'

export interface ReplayBrowserFilters {
  /** Sanitized product route from `REPLAY_BROWSER_ROUTES`, or null for any. */
  route: string | null
  /** `plan` person-property enum, or null for any. */
  plan: string | null
  /** Browser console error predicate, or null for any. */
  error: ReplayBrowserErrorKind | null
  /** Minimum active replay seconds, or null for any duration. */
  minActiveSeconds: number | null
  /** Only sessions that fired `checkout_failed`. */
  checkoutFailure: boolean
}

export const EMPTY_REPLAY_BROWSER_FILTERS: ReplayBrowserFilters = {
  route: null,
  plan: null,
  error: null,
  minActiveSeconds: null,
  checkoutFailure: false,
}

/**
 * Safe, sanitized route filters. This deliberately reuses the triage route
 * list, which excludes `/workspace/:resumeId/edit`, `/r/:token`,
 * `/u/:username`, `/share/:token`, `/portfolio/:username`, and `/try`.
 */
export const REPLAY_BROWSER_ROUTES: ReadonlyArray<{ label: string; path: string }> =
  REPLAY_TRIAGE_ROUTES

export const REPLAY_BROWSER_PLANS: ReadonlyArray<{ label: string; key: string }> =
  REPLAY_TRIAGE_PLANS

export const REPLAY_BROWSER_DURATION_OPTIONS: ReadonlyArray<{ value: number; label: string }> = [
  { value: 60, label: 'Over 1 minute' },
  { value: LONG_SESSION_MIN_ACTIVE_SECONDS, label: 'Over 2 minutes' },
  { value: 300, label: 'Over 5 minutes' },
  { value: 600, label: 'Over 10 minutes' },
]

const ALLOWED_ROUTE_PATHS = new Set(REPLAY_BROWSER_ROUTES.map((route) => route.path))
const ALLOWED_PLAN_KEYS = new Set(REPLAY_BROWSER_PLANS.map((plan) => plan.key))
const MIN_ACTIVE_SECONDS_FLOOR = 30
const MIN_ACTIVE_SECONDS_CEILING = 3_600

/**
 * Defensive matcher for surfaces that must never appear in the replay browser.
 * `isReplayBrowserRoute` is the primary guard (an exact allowlist); this helper
 * also lets the view state the exclusion policy and lets tests assert it.
 */
const BLOCKED_SURFACE = /^\/(?:workspace|workspaces|try|r|u|share|portfolio)(?:\/|$)/i

export function isBlockedReplaySurface(path: string): boolean {
  return BLOCKED_SURFACE.test(path)
}

export function isReplayBrowserRoute(path: string): boolean {
  return ALLOWED_ROUTE_PATHS.has(path) && !isBlockedReplaySurface(path)
}

function normalizeActiveSeconds(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null
  return Math.min(
    MIN_ACTIVE_SECONDS_CEILING,
    Math.max(MIN_ACTIVE_SECONDS_FLOOR, Math.round(value)),
  )
}

/**
 * Coerce arbitrary input (including tampered saved-filter storage) into the
 * closed filter contract. Unknown routes, plans, errors, and durations are
 * dropped rather than forwarded to PostHog.
 */
export function normalizeReplayBrowserFilters(
  input?: Partial<ReplayBrowserFilters> | null,
): ReplayBrowserFilters {
  if (!input) return { ...EMPTY_REPLAY_BROWSER_FILTERS }
  const route = typeof input.route === 'string' && isReplayBrowserRoute(input.route)
    ? input.route
    : null
  const plan = typeof input.plan === 'string' && ALLOWED_PLAN_KEYS.has(input.plan)
    ? input.plan
    : null
  return {
    route,
    plan,
    error: input.error === 'console' ? 'console' : null,
    minActiveSeconds: normalizeActiveSeconds(input.minActiveSeconds),
    checkoutFailure: input.checkoutFailure === true,
  }
}

function buildFilterGroup(
  filters: ReplayBrowserFilters,
): ReplayUniversalFilter['filter_group'] | null {
  const values: Array<ReplayEventFilter | ReplayPropertyFilter> = []
  if (filters.checkoutFailure) {
    values.push({ id: 'checkout_failed', type: 'events', order: 0, name: 'checkout_failed' })
  }
  if (filters.error === 'console') {
    values.push({ key: 'level', operator: 'exact', type: 'log_entry', value: ['error'] })
  }
  if (filters.route) {
    values.push({
      key: '$current_url',
      operator: 'icontains',
      type: 'event',
      value: filters.route,
    })
  }
  if (filters.plan) {
    values.push({ key: 'plan', operator: 'exact', type: 'person', value: [filters.plan] })
  }
  if (values.length === 0) return null
  return { type: 'AND', values: [{ type: 'AND', values }] }
}

/** Build one replay-home URL with every selected filter combined under AND. */
export function buildReplayBrowserUrl(
  config: ReplayLinkConfig,
  filters: Partial<ReplayBrowserFilters>,
): string {
  const normalized = normalizeReplayBrowserFilters(filters)
  const overrides: Partial<ReplayUniversalFilter> = {}
  const filterGroup = buildFilterGroup(normalized)
  if (filterGroup) overrides.filter_group = filterGroup
  if (normalized.minActiveSeconds !== null) {
    overrides.duration = [
      {
        key: 'active_seconds',
        operator: 'gt',
        type: 'recording',
        value: normalized.minActiveSeconds,
      },
    ]
  }
  return buildReplayUrl(config, overrides)
}

export interface ReplayBrowserSavedFilter {
  id: string
  label: string
  description: string
  filters: ReplayBrowserFilters
}

/**
 * Curated saved filters for the common triage dimensions. They are ordinary
 * combinations of the closed filter contract, so they remain auditable and can
 * be resolved against any configured project/date range.
 */
export const REPLAY_BROWSER_SAVED_FILTERS: ReadonlyArray<ReplayBrowserSavedFilter> = [
  {
    id: 'checkout-failures',
    label: 'Checkout failures',
    description: 'Sessions that fired checkout_failed.',
    filters: { ...EMPTY_REPLAY_BROWSER_FILTERS, checkoutFailure: true },
  },
  {
    id: 'console-errors',
    label: 'Console errors',
    description: 'Sessions with a browser console error.',
    filters: { ...EMPTY_REPLAY_BROWSER_FILTERS, error: 'console' },
  },
  {
    id: 'long-sessions',
    label: 'Long sessions',
    description: 'Sessions with more than two active minutes.',
    filters: {
      ...EMPTY_REPLAY_BROWSER_FILTERS,
      minActiveSeconds: LONG_SESSION_MIN_ACTIVE_SECONDS,
    },
  },
  {
    id: 'dashboard-errors',
    label: 'Dashboard errors',
    description: 'Console errors on the dashboard.',
    filters: { ...EMPTY_REPLAY_BROWSER_FILTERS, route: '/dashboard', error: 'console' },
  },
  {
    id: 'billing-errors',
    label: 'Billing errors',
    description: 'Console errors on billing.',
    filters: { ...EMPTY_REPLAY_BROWSER_FILTERS, route: '/billing', error: 'console' },
  },
  {
    id: 'pricing-errors',
    label: 'Pricing errors',
    description: 'Console errors on pricing.',
    filters: { ...EMPTY_REPLAY_BROWSER_FILTERS, route: '/pricing', error: 'console' },
  },
  {
    id: 'templates-errors',
    label: 'Template errors',
    description: 'Console errors on templates.',
    filters: { ...EMPTY_REPLAY_BROWSER_FILTERS, route: '/templates', error: 'console' },
  },
  {
    id: 'billing-checkout-failures',
    label: 'Billing checkout failures',
    description: 'Checkout failures while viewing billing.',
    filters: {
      ...EMPTY_REPLAY_BROWSER_FILTERS,
      route: '/billing',
      checkoutFailure: true,
    },
  },
  {
    id: 'pro-console-errors',
    label: 'Pro plan errors',
    description: 'Console errors from users on the pro plan.',
    filters: { ...EMPTY_REPLAY_BROWSER_FILTERS, plan: 'pro', error: 'console' },
  },
  {
    id: 'team-long-sessions',
    label: 'Team long sessions',
    description: 'Team-plan sessions longer than five active minutes.',
    filters: {
      ...EMPTY_REPLAY_BROWSER_FILTERS,
      plan: 'team',
      minActiveSeconds: 300,
    },
  },
]

export interface ReplayBrowserSavedLink extends ReplayBrowserSavedFilter {
  href: string
}

/** Resolve every saved filter against the configured project and date range. */
export function replayBrowserSavedFilterLinks(
  config: ReplayLinkConfig,
): ReplayBrowserSavedLink[] {
  return REPLAY_BROWSER_SAVED_FILTERS.map((saved) => ({
    ...saved,
    filters: normalizeReplayBrowserFilters(saved.filters),
    href: buildReplayBrowserUrl(config, saved.filters),
  }))
}

/** Human-readable summary used for the active-filter line and screen readers. */
export function describeReplayBrowserFilters(
  filters?: Partial<ReplayBrowserFilters> | null,
): string {
  const normalized = normalizeReplayBrowserFilters(filters)
  const parts: string[] = []
  const route = REPLAY_BROWSER_ROUTES.find((item) => item.path === normalized.route)
  const plan = REPLAY_BROWSER_PLANS.find((item) => item.key === normalized.plan)
  if (route) parts.push(route.label)
  if (plan) parts.push(`${plan.label} plan`)
  if (normalized.error === 'console') parts.push('console errors')
  if (normalized.minActiveSeconds !== null) {
    parts.push(`over ${Math.round(normalized.minActiveSeconds / 60)} active minutes`)
  }
  if (normalized.checkoutFailure) parts.push('checkout failures')
  return parts.length > 0 ? parts.join(' · ') : 'All replays'
}

/**
 * Status copy rendered beside the browser. Keeping it here makes the policy
 * contract testable and prevents the view from drifting into a raw-replay or
 * disable-masking design.
 */
export const REPLAY_BROWSER_CONSENT_COVERAGE = {
  model: 'Opt-in only',
  gatedRoutes: 'All replay-capable product routes',
  captureBeforeConsent: 'Disabled',
  withdrawal: 'Stops recording immediately',
  excludedSurfaces: [
    'Résumé editor',
    'Guest try editor',
    'Public share',
    'Portfolio',
    'Recruiter workspace',
  ],
} as const

export const REPLAY_BROWSER_MASKING_POLICY = {
  textNodes: 'All masked',
  inputs: 'All masked',
  elementAttributes: 'All masked',
  projectSetting: 'Total privacy',
  disableMasking: 'Not available',
} as const
