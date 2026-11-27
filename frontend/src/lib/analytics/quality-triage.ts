/**
 * Pure contract for the admin Quality triage view.
 *
 * PostHog owns the exception, rage-click, and dead-click data. This module
 * never fetches or embeds that data: it describes the saved insights an
 * operator can open and builds the filtered PostHog URLs for the selected
 * route, release, and 7/30-day range.
 *
 * Guardrails encoded here:
 *  - Route values are a closed allowlist of sanitized product paths. Document,
 *    share, portfolio, and guest-editor surfaces can never be selected.
 *  - Release values are bounded, low-cardinality identifiers. Free-form text,
 *    emails, tokens, and paths are rejected.
 *  - The view only knows about aggregate issue classes. It never requests a
 *    person, session, or event history, and it has no unmask control.
 *  - Counts below five are suppressed, and missing telemetry is labelled
 *    rather than rendered as zero.
 */

import {
  buildReplayUrl,
  DEFAULT_POSTHOG_UI_HOST,
  REPLAY_TRIAGE_ROUTES,
  type ReplayEventFilter,
  type ReplayLinkConfig,
  type ReplayPropertyFilter,
  type ReplayUniversalFilter,
} from './replay-links'

export const QUALITY_RANGES = [7, 30] as const
export type QualityRange = (typeof QUALITY_RANGES)[number]

/** Minimum aggregate cohort. Values 1-4 are never published. */
export const QUALITY_MIN_COHORT_SIZE = 5

export interface QualityRoute {
  label: string
  path: string
}

/**
 * Sanitized product routes surfaced in the route matrix. `/`, document,
 * share, portfolio, and guest-editor paths are deliberately absent: replay is
 * blocked there, so a triage link would either be empty or expose document
 * context.
 */
export const QUALITY_ROUTES: ReadonlyArray<QualityRoute> = [
  ...REPLAY_TRIAGE_ROUTES,
  { label: 'Login', path: '/login' },
  { label: 'Sign up', path: '/signup' },
]

const QUALITY_ROUTE_PATHS = new Set(QUALITY_ROUTES.map((route) => route.path))
const BLOCKED_QUALITY_SURFACE = /^\/(?:workspace|workspaces|try|r|u|share|portfolio)(?:\/|$)/i
const QUALITY_RELEASE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/

/** Defensive matcher for surfaces that must never appear in quality links. */
export function isBlockedQualityRoute(path: string): boolean {
  const clean = path.split('?')[0].split('#')[0] || '/'
  return BLOCKED_QUALITY_SURFACE.test(clean)
}

/** Coerce an arbitrary value into the closed route allowlist, or null. */
export function normalizeQualityRoute(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const route = value.trim()
  if (!QUALITY_ROUTE_PATHS.has(route) || isBlockedQualityRoute(route)) return null
  return route
}

/** Coerce an arbitrary value into a bounded release identifier, or null. */
export function normalizeQualityRelease(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const release = value.trim()
  if (/^(?:phc_|phx_|sk-|bearer)/i.test(release)) return null
  return QUALITY_RELEASE_PATTERN.test(release) ? release : null
}

export type QualityIssueKind = 'js_error' | 'rage_click' | 'dead_click'

export interface QualityIssueDescriptor {
  kind: QualityIssueKind
  label: string
  shortLabel: string
  description: string
  /** PostHog event counted by the saved insight. */
  event: string
  /** PostHog event used to filter the replay list. */
  replayEvent: string
  /** Guarded error-class property added by the analytics boundary, if any. */
  errorTypeProperty: string | null
  /** Whether PostHog error tracking is a useful secondary destination. */
  errorTracking: boolean
  insightName: string
  missingTelemetry: string
}

export const QUALITY_ISSUES: ReadonlyArray<QualityIssueDescriptor> = [
  {
    kind: 'js_error',
    label: 'JavaScript errors',
    shortLabel: 'JS errors',
    description:
      'Uncaught exceptions and unhandled rejections, grouped by sanitized error class, route, and release.',
    event: '$exception',
    replayEvent: '$exception',
    errorTypeProperty: 'error_type',
    errorTracking: true,
    insightName: 'Latexy quality - JS errors by route and release',
    missingTelemetry: 'No PostHog exception telemetry is configured for this project.',
  },
  {
    kind: 'rage_click',
    label: 'Rage clicks',
    shortLabel: 'Rage clicks',
    description:
      'Repeated rapid clicks on the same element, broken down by sanitized route and release.',
    event: '$rageclick',
    replayEvent: '$rageclick',
    errorTypeProperty: null,
    errorTracking: false,
    insightName: 'Latexy quality - rage clicks by route and release',
    missingTelemetry: 'No PostHog rage-click telemetry is configured for this project.',
  },
  {
    kind: 'dead_click',
    label: 'Dead clicks',
    shortLabel: 'Dead clicks',
    description:
      'Clicks with no visible response, broken down by sanitized route and release.',
    event: '$dead_click',
    replayEvent: '$dead_click',
    errorTypeProperty: null,
    errorTracking: false,
    insightName: 'Latexy quality - dead clicks by route and release',
    missingTelemetry: 'No PostHog dead-click telemetry is configured for this project.',
  },
]

export interface QualityTriageFilters {
  /** Sanitized product route, or null for all routes. */
  route: string | null
  /** Bounded release tag, or null for all releases. */
  release: string | null
}

export const EMPTY_QUALITY_FILTERS: QualityTriageFilters = {
  route: null,
  release: null,
}

export function normalizeQualityFilters(
  input?: Partial<QualityTriageFilters> | null,
): QualityTriageFilters {
  return {
    route: normalizeQualityRoute(input?.route),
    release: normalizeQualityRelease(input?.release),
  }
}

export interface QualityTrendsPropertyFilter {
  key: string
  operator: 'exact'
  type: 'event'
  value: string[]
}

export interface QualityTrendsQuery {
  kind: 'InsightVizNode'
  source: {
    kind: 'TrendsQuery'
    interval: 'day'
    dateRange: { date_from: string; date_to: null }
    filterTestAccounts: boolean
    series: Array<{
      kind: 'EventsNode'
      event: string
      name: string
      math: 'total'
    }>
    properties: QualityTrendsPropertyFilter[]
    breakdownFilter: {
      breakdown_type: 'event'
      breakdowns: Array<{ type: 'event'; property: string }>
      breakdown_limit: number
    }
    trendsFilter: { display: 'ActionsTable' }
  }
  full: boolean
}

function boundedDays(days: number): number {
  if (!Number.isFinite(days)) return 30
  return Math.min(365, Math.max(1, Math.round(days)))
}

/**
 * Build the PostHog trends query behind a saved insight descriptor. The query
 * is an aggregate table: route, optional release, and optional error class.
 * There is no distinct-id, person, session, or event-history column.
 */
export function buildQualityTrendsQuery(
  issue: QualityIssueDescriptor,
  filters?: Partial<QualityTriageFilters> | null,
  days = 30,
): QualityTrendsQuery {
  const normalized = normalizeQualityFilters(filters)
  const properties: QualityTrendsPropertyFilter[] = []
  if (normalized.route) {
    properties.push({
      key: 'route',
      operator: 'exact',
      type: 'event',
      value: [normalized.route],
    })
  }
  if (normalized.release) {
    properties.push({
      key: '$release_id',
      operator: 'exact',
      type: 'event',
      value: [normalized.release],
    })
  }

  const breakdowns: Array<{ type: 'event'; property: string }> = [
    { type: 'event', property: 'route' },
  ]
  if (normalized.release) {
    breakdowns.push({ type: 'event', property: '$release_id' })
  }
  if (issue.errorTypeProperty) {
    breakdowns.push({ type: 'event', property: issue.errorTypeProperty })
  }

  return {
    kind: 'InsightVizNode',
    source: {
      kind: 'TrendsQuery',
      interval: 'day',
      dateRange: { date_from: `-${boundedDays(days)}d`, date_to: null },
      filterTestAccounts: true,
      series: [
        {
          kind: 'EventsNode',
          event: issue.event,
          name: issue.label,
          math: 'total',
        },
      ],
      properties,
      breakdownFilter: {
        breakdown_type: 'event',
        breakdowns,
        breakdown_limit: 25,
      },
      trendsFilter: { display: 'ActionsTable' },
    },
    full: true,
  }
}

function posthogHost(config: ReplayLinkConfig): string {
  return (config.uiHost ?? DEFAULT_POSTHOG_UI_HOST).replace(/\/+$/, '')
}

/** Open the saved trends insight with the matching route/release filters. */
export function buildQualityTrendsUrl(
  config: ReplayLinkConfig,
  issue: QualityIssueDescriptor,
  filters?: Partial<QualityTriageFilters> | null,
): string {
  const query = buildQualityTrendsQuery(issue, filters, config.days)
  return `${posthogHost(config)}/project/${encodeURIComponent(config.projectId)}/insights/new?insight=TRENDS&q=${encodeURIComponent(JSON.stringify(query))}`
}

function replayFilterGroup(
  values: Array<ReplayEventFilter | ReplayPropertyFilter>,
): ReplayUniversalFilter['filter_group'] {
  return { type: 'AND', values: [{ type: 'AND', values }] }
}

/** Open replays containing the issue event on the matching route/release. */
export function buildQualityReplayUrl(
  config: ReplayLinkConfig,
  issue: QualityIssueDescriptor,
  filters?: Partial<QualityTriageFilters> | null,
): string {
  const normalized = normalizeQualityFilters(filters)
  const values: Array<ReplayEventFilter | ReplayPropertyFilter> = [
    {
      id: issue.replayEvent,
      type: 'events',
      order: 0,
      name: issue.replayEvent,
    },
  ]
  if (normalized.route) {
    values.push({
      key: '$current_url',
      operator: 'icontains',
      type: 'event',
      value: normalized.route,
    })
  }
  if (normalized.release) {
    values.push({
      key: '$release_id',
      operator: 'exact',
      type: 'event',
      value: [normalized.release],
    })
  }
  return buildReplayUrl(config, { filter_group: replayFilterGroup(values) })
}

/** PostHog error tracking is only linked for the exception issue. */
export function buildQualityErrorTrackingUrl(config: ReplayLinkConfig): string {
  return `${posthogHost(config)}/project/${encodeURIComponent(config.projectId)}/error-tracking`
}

/**
 * Sanitized identity shared by the backend error feed and PostHog link
 * builders. Values that are not bounded identifiers/routes are dropped rather
 * than echoed into a URL.
 */
export interface QualityErrorGroupIdentity {
  route?: string | null
  release?: string | null
  error_class?: string | null
}

const QUALITY_ERROR_CLASS_PATTERN = /^[A-Za-z][A-Za-z0-9_.:-]{0,79}$/

export function normalizeQualityErrorClass(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const errorClass = value.trim()
  return QUALITY_ERROR_CLASS_PATTERN.test(errorClass) ? errorClass : null
}

/**
 * Open masked replays that fired `$exception`, filtered by the same sanitized
 * route, release, and error class as a backend feed row. No free-form text,
 * person property, or unmask control is included.
 */
export function buildQualityErrorGroupReplayUrl(
  config: ReplayLinkConfig,
  group: QualityErrorGroupIdentity,
): string {
  const route = normalizeQualityRoute(group.route)
  const release = normalizeQualityRelease(group.release)
  const errorClass = normalizeQualityErrorClass(group.error_class)
  const values: Array<ReplayEventFilter | ReplayPropertyFilter> = [
    { id: '$exception', type: 'events', order: 0, name: '$exception' },
  ]
  if (route) {
    values.push({
      key: '$current_url',
      operator: 'icontains',
      type: 'event',
      value: route,
    })
  }
  if (release) {
    values.push({
      key: '$release_id',
      operator: 'exact',
      type: 'event',
      value: [release],
    })
  }
  if (errorClass) {
    values.push({
      key: 'error_type',
      operator: 'exact',
      type: 'event',
      value: [errorClass],
    })
  }
  return buildReplayUrl(config, { filter_group: replayFilterGroup(values) })
}

/**
 * Open PostHog error tracking with a bounded search term. Filtering is a
 * best-effort search; the grouped issue itself remains PostHog's source of
 * truth. Only sanitized identifiers are ever placed in the URL.
 */
export function buildQualityErrorGroupErrorTrackingUrl(
  config: ReplayLinkConfig,
  group: QualityErrorGroupIdentity,
): string {
  const terms = [
    normalizeQualityErrorClass(group.error_class),
    normalizeQualityRoute(group.route),
    normalizeQualityRelease(group.release),
  ].filter((value): value is string => Boolean(value))
  const suffix = terms.length > 0 ? `?search=${encodeURIComponent(terms.join(' '))}` : ''
  return `${posthogHost(config)}/project/${encodeURIComponent(config.projectId)}/error-tracking${suffix}`
}

export interface QualitySavedInsight {
  id: string
  label: string
  shortLabel: string
  description: string
  event: string
  insightName: string
  breakdowns: string[]
  trendsHref: string
  replayHref: string
  errorTrackingHref: string | null
  missingTelemetry: string
}

/**
 * Resolve the three saved-insight descriptors against a configured project,
 * selected range, route, and release. Each descriptor is an ordinary
 * aggregate PostHog view; the returned object carries no person-level data.
 */
export function qualitySavedInsights(
  config: ReplayLinkConfig,
  filters?: Partial<QualityTriageFilters> | null,
): QualitySavedInsight[] {
  const normalized = normalizeQualityFilters(filters)
  return QUALITY_ISSUES.map((issue) => {
    const breakdowns = ['route']
    if (normalized.release) breakdowns.push('$release_id')
    if (issue.errorTypeProperty) breakdowns.push(issue.errorTypeProperty)
    return {
      id: issue.kind,
      label: issue.label,
      shortLabel: issue.shortLabel,
      description: issue.description,
      event: issue.event,
      insightName: issue.insightName,
      breakdowns,
      trendsHref: buildQualityTrendsUrl(config, issue, normalized),
      replayHref: buildQualityReplayUrl(config, issue, normalized),
      errorTrackingHref: issue.errorTracking ? buildQualityErrorTrackingUrl(config) : null,
      missingTelemetry: issue.missingTelemetry,
    }
  })
}

export interface QualityRouteRow {
  label: string
  path: string
  savedInsights: QualitySavedInsight[]
}

/** Resolve one row per allowed route for the admin route matrix. */
export function qualityRouteRows(
  config: ReplayLinkConfig,
  filters?: Partial<QualityTriageFilters> | null,
): QualityRouteRow[] {
  const normalized = normalizeQualityFilters(filters)
  return QUALITY_ROUTES.map((route) => ({
    label: route.label,
    path: route.path,
    savedInsights: qualitySavedInsights(config, { ...normalized, route: route.path }),
  }))
}

export function describeQualityFilters(
  filters?: Partial<QualityTriageFilters> | null,
): string {
  const normalized = normalizeQualityFilters(filters)
  const route = QUALITY_ROUTES.find((item) => item.path === normalized.route)
  return [
    route ? route.label : 'All routes',
    normalized.release ? `release ${normalized.release}` : 'all releases',
  ].join(' · ')
}

export interface QualityTelemetryState {
  status: 'available' | 'not_configured'
  label: string
  detail: string
  missing: boolean
  releaseLabel: string
  suppressionLabel: string
}

/**
 * Missing telemetry is a first-class state. It is never converted into a row
 * of zeroes, and the copy says so explicitly.
 */
export function qualityTelemetryState(input: {
  configured: boolean
  release?: string | null
  days?: number
}): QualityTelemetryState {
  const release = normalizeQualityRelease(input.release)
  const suppressionLabel = `Aggregate only · groups with fewer than ${QUALITY_MIN_COHORT_SIZE} events are suppressed`
  if (!input.configured) {
    return {
      status: 'not_configured',
      label: 'Missing telemetry',
      detail:
        'PostHog is not configured for this deployment, so issue counts are unavailable. This is not the same as zero errors.',
      missing: true,
      releaseLabel: release ? `Release ${release}` : 'Release tag unavailable',
      suppressionLabel,
    }
  }
  return {
    status: 'available',
    label: 'PostHog telemetry linked',
    detail:
      'Open a saved insight or replay view for live aggregate counts. Counts are never zero-filled when telemetry is missing.',
    missing: false,
    releaseLabel: release ? `Release ${release}` : 'Release tag not configured',
    suppressionLabel,
  }
}

export interface QualityCount {
  value: number | null
  suppressed: boolean
  missing: boolean
}

/**
 * Suppress a small aggregate before display. `null` means telemetry was not
 * available; a valid zero is distinguishable and is only shown when known.
 */
export function suppressQualityCount(count: number | null | undefined): QualityCount {
  if (count == null || !Number.isFinite(count) || count < 0) {
    return { value: null, suppressed: false, missing: true }
  }
  const value = Math.floor(count)
  if (value > 0 && value < QUALITY_MIN_COHORT_SIZE) {
    return { value: null, suppressed: true, missing: false }
  }
  return { value, suppressed: false, missing: false }
}

export function qualityCountLabel(count: number | null | undefined): string {
  const result = suppressQualityCount(count)
  if (result.missing) return 'Missing telemetry'
  if (result.suppressed) return `Suppressed (<${QUALITY_MIN_COHORT_SIZE})`
  return new Intl.NumberFormat('en-IN').format(result.value ?? 0)
}

export const QUALITY_GUARDRAILS = {
  consent: 'PostHog loads only after analytics consent; withdrawal stops capture and exception autocapture.',
  masking: 'Every text node, input, and element attribute stays masked. There is no unmask switch.',
  excludedSurfaces: [
    'Résumé editor',
    'Guest try editor',
    'Public share',
    'Portfolio',
    'Workspace',
  ],
  perUser:
    'No per-user histories, session scoring, person filters, or raw event payloads are exposed here.',
  suppression: `Route/release groups with fewer than ${QUALITY_MIN_COHORT_SIZE} events are suppressed before interpretation.`,
} as const
