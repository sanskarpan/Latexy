/**
 * Pure catalog and URL contract for the admin PostHog saved insights.
 *
 * PostHog owns funnels, trends, paths, retention, and stickiness. This module
 * never fetches or embeds that data: it describes the aggregate views an admin
 * can open for the selected 7/30/90-day range and builds the matching project
 * URL. The admin Analytics tab renders the resolved links next to the
 * authoritative first-party KPI cards.
 *
 * Guardrails encoded here:
 *  - Every link targets the configured project and carries the selected date
 *    range, either in the insight query (`-7d` / `-30d` / `-90d`) or in the
 *    saved-insight `filters_override`.
 *  - Breakdowns are restricted to a small allowlist of low-cardinality
 *    properties. Emails, names, user/distinct ids, document paths, prompts,
 *    tokens, and person histories are rejected.
 *  - No public share link and no embed token is generated. When the project is
 *    unavailable the catalog is labelled as missing rather than zero-filled,
 *    and the first-party KPI cards are unaffected.
 *  - Aggregate cohorts smaller than five are suppressed before display.
 */

import { DEFAULT_POSTHOG_UI_HOST, type ReplayLinkConfig } from './replay-links'

export const POSTHOG_INSIGHT_RANGES = [7, 30, 90] as const
export type PostHogInsightRange = (typeof POSTHOG_INSIGHT_RANGES)[number]

/** Minimum aggregate cohort. Values 1-4 are never published. */
export const MIN_INSIGHT_COHORT_SIZE = 5

export type SavedInsightKind = 'funnel' | 'trends' | 'paths' | 'retention' | 'stickiness'

export type PostHogInsightType = 'FUNNELS' | 'TRENDS' | 'PATHS' | 'RETENTION' | 'STICKINESS'

/**
 * Low-cardinality event and person properties that are safe to group by.
 *
 * `route` is already templated by the analytics boundary, `plan` / `provider` /
 * `model` / `status` / `format` / `billing_period` are enums, and `feature` /
 * `event_type` are bounded product vocabulary. None of them can identify a
 * person or carry document content.
 */
export const SAFE_INSIGHT_BREAKDOWNS = [
  'route',
  'plan',
  'feature',
  'event_type',
  'status',
  'format',
  'provider',
  'model',
  'billing_period',
  '$release_id',
  '$browser',
  '$os',
  '$device_type',
] as const

const SAFE_INSIGHT_BREAKDOWN_SET = new Set<string>(SAFE_INSIGHT_BREAKDOWNS)

// Defense in depth for a caller that bypasses the allowlist. Matches the
// frontend/backend analytics sanitizers and the personal-data guardrails.
const PII_BREAKDOWN_PATTERN =
  /(email|phone|address|resume|latex|content|prompt|text|token|secret|password|auth|cookie|ssn|birth|salary|job.?description|cover.?letter|user.?id|distinct.?id|person|\bip\b|name)/i

export function isSafeInsightBreakdown(value: string): boolean {
  return SAFE_INSIGHT_BREAKDOWN_SET.has(value) && !PII_BREAKDOWN_PATTERN.test(value)
}

export interface SavedInsightDescriptor {
  kind: SavedInsightKind
  label: string
  shortLabel: string
  description: string
  insightType: PostHogInsightType
  /** Env var that carries the optional saved PostHog short id. */
  savedInsightEnvVar: string
  /** Bounded event vocabulary used by the aggregate view. */
  events: readonly string[]
  /** Allowlisted aggregate breakdowns; empty for an unsegmented view. */
  breakdowns: readonly string[]
  minimumCohortSize: number
}

/**
 * The five saved-insight descriptors surfaced from the admin Analytics tab.
 *
 * The event names match the existing PostHog taxonomy in docs/POSTHOG.md. The
 * catalog is intentionally static and typed: a saved id is an optional
 * configuration detail, not a reason to mirror PostHog data into Latexy.
 */
export const SAVED_INSIGHT_CATALOG: ReadonlyArray<SavedInsightDescriptor> = [
  {
    kind: 'funnel',
    label: 'Activation funnel',
    shortLabel: 'Funnel',
    description:
      'Landing view → product event → compile → checkout start. Aggregate conversion across the selected period.',
    insightType: 'FUNNELS',
    savedInsightEnvVar: 'NEXT_PUBLIC_POSTHOG_INSIGHT_FUNNEL_ID',
    events: ['$pageview', 'product_event', 'compilation_tracked', 'checkout_started'],
    breakdowns: [],
    minimumCohortSize: MIN_INSIGHT_COHORT_SIZE,
  },
  {
    kind: 'trends',
    label: 'Product event trends',
    shortLabel: 'Trends',
    description:
      'Daily compile, optimization, and checkout activity, optionally grouped by sanitized route.',
    insightType: 'TRENDS',
    savedInsightEnvVar: 'NEXT_PUBLIC_POSTHOG_INSIGHT_TRENDS_ID',
    events: ['compilation_tracked', 'optimization_tracked', 'checkout_started'],
    breakdowns: ['route'],
    minimumCohortSize: MIN_INSIGHT_COHORT_SIZE,
  },
  {
    kind: 'paths',
    label: 'Navigation paths',
    shortLabel: 'Paths',
    description:
      'Aggregate page paths from the dashboard into the product. Document, share, portfolio, and workspace surfaces are excluded at capture.',
    insightType: 'PATHS',
    savedInsightEnvVar: 'NEXT_PUBLIC_POSTHOG_INSIGHT_PATHS_ID',
    events: ['$pageview'],
    breakdowns: [],
    minimumCohortSize: MIN_INSIGHT_COHORT_SIZE,
  },
  {
    kind: 'retention',
    label: 'Weekly retention',
    shortLabel: 'Retention',
    description:
      'Weekly retention after a user first compiles a document. Aggregate cohorts only; no person rows are returned to the admin page.',
    insightType: 'RETENTION',
    savedInsightEnvVar: 'NEXT_PUBLIC_POSTHOG_INSIGHT_RETENTION_ID',
    events: ['compilation_tracked'],
    breakdowns: [],
    minimumCohortSize: MIN_INSIGHT_COHORT_SIZE,
  },
  {
    kind: 'stickiness',
    label: 'Feature stickiness',
    shortLabel: 'Stickiness',
    description:
      'How many days users return to a feature, grouped by the bounded feature key for the selected period.',
    insightType: 'STICKINESS',
    savedInsightEnvVar: 'NEXT_PUBLIC_POSTHOG_INSIGHT_STICKINESS_ID',
    events: ['feature_used'],
    breakdowns: ['feature'],
    minimumCohortSize: MIN_INSIGHT_COHORT_SIZE,
  },
]

export type SavedInsightIdMap = Partial<Record<SavedInsightKind, string>>

export interface SavedInsightLinkConfig extends ReplayLinkConfig {
  /** Optional saved PostHog short ids, keyed by catalog descriptor. */
  savedInsightIds?: SavedInsightIdMap
}

const SAVED_INSIGHT_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/
const SAVED_INSIGHT_TOKEN_PREFIX = /^(?:phc_|phx_|sk-|bearer)/i

/** Accept a bounded PostHog short id or reject it rather than building a URL. */
export function normalizeSavedInsightId(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const id = value.trim()
  if (SAVED_INSIGHT_TOKEN_PREFIX.test(id)) return null
  if (!SAVED_INSIGHT_ID_PATTERN.test(id)) return null
  return id
}

/** Coerce an arbitrary range into the 1-365 day window used by the admin tab. */
export function boundedInsightDays(days: number): number {
  if (!Number.isFinite(days)) return 30
  return Math.min(365, Math.max(1, Math.round(days)))
}

export function insightDateFrom(days: number): string {
  return `-${boundedInsightDays(days)}d`
}

export interface InsightDateRange {
  date_from: string
  date_to: null
}

export interface InsightEventNode {
  kind: 'EventsNode'
  event: string
  name: string
  math: 'total'
}

export interface InsightBreakdownFilter {
  breakdown_type: 'event'
  breakdowns: Array<{ type: 'event'; property: string }>
  breakdown_limit: number
}

export interface FunnelQuerySource {
  kind: 'FunnelsQuery'
  dateRange: InsightDateRange
  filterTestAccounts: boolean
  series: InsightEventNode[]
  funnelsFilter: {
    funnelVizType: 'steps'
    funnelOrderType: 'ordered'
    funnelStepReference: 'total'
  }
}

export interface TrendsQuerySource {
  kind: 'TrendsQuery'
  interval: 'day'
  dateRange: InsightDateRange
  filterTestAccounts: boolean
  series: InsightEventNode[]
  properties: []
  breakdownFilter?: InsightBreakdownFilter
  trendsFilter: { display: 'ActionsTable' }
}

export interface PathsQuerySource {
  kind: 'PathsQuery'
  dateRange: InsightDateRange
  filterTestAccounts: boolean
  pathsFilter: {
    includeEventTypes: ['$pageview']
    startPoint: '/dashboard'
    pathGrouping: 'path'
    edgeLimit: number
  }
}

export interface RetentionQuerySource {
  kind: 'RetentionQuery'
  dateRange: InsightDateRange
  filterTestAccounts: boolean
  retentionFilter: {
    period: 'Week'
    totalIntervals: number
    targetEntity: { id: string; name: string; type: 'events'; order: number }
    returningEntity: { id: string; name: string; type: 'events'; order: number }
    retentionType: 'retention_recurring'
    minimumOccurrences: number
    display: 'ActionsTable'
  }
}

export interface StickinessQuerySource {
  kind: 'StickinessQuery'
  dateRange: InsightDateRange
  filterTestAccounts: boolean
  series: InsightEventNode[]
  breakdownFilter?: InsightBreakdownFilter
  stickinessFilter: { display: 'ActionsTable'; computedAs: 'dau' }
}

export type SavedInsightQuery =
  | { kind: 'InsightVizNode'; source: FunnelQuerySource; full: true }
  | { kind: 'InsightVizNode'; source: TrendsQuerySource; full: true }
  | { kind: 'InsightVizNode'; source: PathsQuerySource; full: true }
  | { kind: 'InsightVizNode'; source: RetentionQuerySource; full: true }
  | { kind: 'InsightVizNode'; source: StickinessQuerySource; full: true }

function eventNodes(events: readonly string[]): InsightEventNode[] {
  return events.map((event) => ({
    kind: 'EventsNode',
    event,
    name: event,
    math: 'total',
  }))
}

function safeBreakdownFilter(descriptor: SavedInsightDescriptor): InsightBreakdownFilter | undefined {
  const breakdowns = descriptor.breakdowns
    .filter(isSafeInsightBreakdown)
    .map((property) => ({ type: 'event' as const, property }))
  if (breakdowns.length === 0) return undefined
  return {
    breakdown_type: 'event',
    breakdowns,
    breakdown_limit: 25,
  }
}

/**
 * Build the PostHog insight query behind a descriptor. It always embeds the
 * selected range, filters test accounts, and only uses allowlisted aggregate
 * breakdowns. There is no distinct-id, person, session, or event-history
 * column.
 */
export function buildSavedInsightQuery(
  descriptor: SavedInsightDescriptor,
  days: number,
): SavedInsightQuery {
  const dateRange: InsightDateRange = { date_from: insightDateFrom(days), date_to: null }
  const rangeDays = boundedInsightDays(days)

  switch (descriptor.kind) {
    case 'funnel':
      return {
        kind: 'InsightVizNode',
        source: {
          kind: 'FunnelsQuery',
          dateRange,
          filterTestAccounts: true,
          series: eventNodes(descriptor.events),
          funnelsFilter: {
            funnelVizType: 'steps',
            funnelOrderType: 'ordered',
            funnelStepReference: 'total',
          },
        },
        full: true,
      }
    case 'trends': {
      const breakdownFilter = safeBreakdownFilter(descriptor)
      return {
        kind: 'InsightVizNode',
        source: {
          kind: 'TrendsQuery',
          interval: 'day',
          dateRange,
          filterTestAccounts: true,
          series: eventNodes(descriptor.events),
          properties: [],
          ...(breakdownFilter ? { breakdownFilter } : {}),
          trendsFilter: { display: 'ActionsTable' },
        },
        full: true,
      }
    }
    case 'paths':
      return {
        kind: 'InsightVizNode',
        source: {
          kind: 'PathsQuery',
          dateRange,
          filterTestAccounts: true,
          pathsFilter: {
            includeEventTypes: ['$pageview'],
            startPoint: '/dashboard',
            pathGrouping: 'path',
            edgeLimit: 50,
          },
        },
        full: true,
      }
    case 'retention': {
      const targetEvent = descriptor.events[0] ?? 'compilation_tracked'
      const entity = { id: targetEvent, name: targetEvent, type: 'events' as const, order: 0 }
      return {
        kind: 'InsightVizNode',
        source: {
          kind: 'RetentionQuery',
          dateRange,
          filterTestAccounts: true,
          retentionFilter: {
            period: 'Week',
            // Keep the window useful for the longest admin range without
            // returning an unbounded cohort table.
            totalIntervals: Math.max(8, Math.ceil(rangeDays / 7)),
            targetEntity: entity,
            returningEntity: { ...entity },
            retentionType: 'retention_recurring',
            minimumOccurrences: 1,
            display: 'ActionsTable',
          },
        },
        full: true,
      }
    }
    case 'stickiness': {
      const breakdownFilter = safeBreakdownFilter(descriptor)
      return {
        kind: 'InsightVizNode',
        source: {
          kind: 'StickinessQuery',
          dateRange,
          filterTestAccounts: true,
          series: eventNodes(descriptor.events),
          ...(breakdownFilter ? { breakdownFilter } : {}),
          stickinessFilter: { display: 'ActionsTable', computedAs: 'dau' },
        },
        full: true,
      }
    }
  }
}

function postHogHost(uiHost?: string): string {
  const raw = (uiHost ?? DEFAULT_POSTHOG_UI_HOST).trim().replace(/\/+$/, '')
  if (!raw) return DEFAULT_POSTHOG_UI_HOST
  try {
    const url = new URL(raw)
    if (url.protocol === 'https:' || url.protocol === 'http:') {
      return `${url.origin}${url.pathname.replace(/\/+$/, '')}`
    }
  } catch {
    // Fall through to the configured default rather than linking an invalid host.
  }
  return DEFAULT_POSTHOG_UI_HOST
}

function projectBase(config: SavedInsightLinkConfig): string {
  return `${postHogHost(config.uiHost)}/project/${encodeURIComponent(config.projectId)}`
}

/**
 * Open a new, prefilled insight of the descriptor's type. This is the fallback
 * when no saved short id is configured, so the admin can still reach the view
 * in one click and save it in PostHog if desired.
 */
export function buildDraftSavedInsightUrl(
  config: SavedInsightLinkConfig,
  descriptor: SavedInsightDescriptor,
): string {
  const query = buildSavedInsightQuery(descriptor, config.days)
  return `${projectBase(config)}/insights/new?insight=${descriptor.insightType}&q=${encodeURIComponent(JSON.stringify(query))}`
}

/**
 * Open a saved insight for the selected project and date range. The range is
 * supplied through PostHog's dashboard `filters_override` parameter, which is
 * the supported way to re-run a saved insight with a different date range
 * without editing it.
 */
export function buildSavedInsightUrl(
  config: SavedInsightLinkConfig,
  descriptor: SavedInsightDescriptor,
  savedInsightId?: string | null,
): string | null {
  const id = normalizeSavedInsightId(savedInsightId)
  if (!id) return null
  const filtersOverride = {
    date_from: insightDateFrom(config.days),
    date_to: null,
  }
  return `${projectBase(config)}/insights/${encodeURIComponent(id)}?filters_override=${encodeURIComponent(JSON.stringify(filtersOverride))}`
}

export interface ResolvedSavedInsight {
  id: SavedInsightKind
  label: string
  shortLabel: string
  description: string
  insightType: PostHogInsightType
  events: readonly string[]
  breakdowns: readonly string[]
  minimumCohortSize: number
  savedInsightId: string | null
  savedHref: string | null
  draftHref: string
  href: string
  mode: 'saved' | 'draft'
  dateFrom: string
  days: number
  projectId: string
}

/** Resolve one descriptor against the configured project, range, and saved id. */
export function resolveSavedInsight(
  config: SavedInsightLinkConfig,
  descriptor: SavedInsightDescriptor,
): ResolvedSavedInsight {
  const savedInsightId = normalizeSavedInsightId(config.savedInsightIds?.[descriptor.kind])
  const savedHref = buildSavedInsightUrl(config, descriptor, savedInsightId)
  const draftHref = buildDraftSavedInsightUrl(config, descriptor)
  return {
    id: descriptor.kind,
    label: descriptor.label,
    shortLabel: descriptor.shortLabel,
    description: descriptor.description,
    insightType: descriptor.insightType,
    events: descriptor.events,
    breakdowns: descriptor.breakdowns,
    minimumCohortSize: descriptor.minimumCohortSize,
    savedInsightId,
    savedHref,
    draftHref,
    href: savedHref ?? draftHref,
    mode: savedHref ? 'saved' : 'draft',
    dateFrom: insightDateFrom(config.days),
    days: boundedInsightDays(config.days),
    projectId: config.projectId,
  }
}

/** Resolve every catalog entry for the admin Analytics tab. */
export function resolveSavedInsightCatalog(config: SavedInsightLinkConfig): ResolvedSavedInsight[] {
  return SAVED_INSIGHT_CATALOG.map((descriptor) => resolveSavedInsight(config, descriptor))
}

export interface SavedInsightCatalogState {
  status: 'configured' | 'not_configured'
  configured: boolean
  label: string
  detail: string
  fallbackLabel: string
  cohortLabel: string
  days: number
  savedCount: number
  draftCount: number
}

/**
 * Missing configuration is a first-class state. The first-party KPI cards keep
 * loading; only the optional PostHog link panel is labelled unavailable.
 */
export function savedInsightCatalogState(input: {
  config: SavedInsightLinkConfig | null
  days: number
}): SavedInsightCatalogState {
  const days = boundedInsightDays(input.days)
  const cohortLabel = `Aggregate only · groups with fewer than ${MIN_INSIGHT_COHORT_SIZE} are suppressed`
  if (!input.config) {
    return {
      status: 'not_configured',
      configured: false,
      label: 'PostHog not configured',
      detail:
        'PostHog is not configured for this deployment. The first-party KPI cards above still load from the Latexy database; only these optional exploration links are unavailable.',
      fallbackLabel: 'First-party KPIs unaffected',
      cohortLabel,
      days,
      savedCount: 0,
      draftCount: 0,
    }
  }

  const savedCount = SAVED_INSIGHT_CATALOG.filter((descriptor) =>
    normalizeSavedInsightId(input.config?.savedInsightIds?.[descriptor.kind]),
  ).length
  return {
    status: 'configured',
    configured: true,
    label: 'PostHog insights linked',
    detail:
      'Each view opens the configured PostHog project with the selected date range. Saved ids open the saved insight; missing ids open a prefilled draft.',
    fallbackLabel: 'First-party KPIs remain authoritative',
    cohortLabel,
    days,
    savedCount,
    draftCount: SAVED_INSIGHT_CATALOG.length - savedCount,
  }
}

export interface InsightCount {
  value: number | null
  suppressed: boolean
  missing: boolean
}

/**
 * Suppress a small aggregate before display. `null` means telemetry was not
 * available; a valid zero is distinguishable and is only shown when known.
 */
export function suppressInsightCount(count: number | null | undefined): InsightCount {
  if (count == null || !Number.isFinite(count) || count < 0) {
    return { value: null, suppressed: false, missing: true }
  }
  const value = Math.floor(count)
  if (value > 0 && value < MIN_INSIGHT_COHORT_SIZE) {
    return { value: null, suppressed: true, missing: false }
  }
  return { value, suppressed: false, missing: false }
}

export function insightCountLabel(count: number | null | undefined): string {
  const result = suppressInsightCount(count)
  if (result.missing) return 'Missing telemetry'
  if (result.suppressed) return `Suppressed (<${MIN_INSIGHT_COHORT_SIZE})`
  return new Intl.NumberFormat('en-IN').format(result.value ?? 0)
}

export const POSTHOG_INSIGHT_GUARDRAILS = {
  adminOnly:
    'Links render only inside the admin Analytics tab, which is gated by the admin role. There is no public page or share action.',
  noPublicSharing:
    'No dashboard or insight share token is generated; every link opens the authenticated PostHog project.',
  piiBreakdowns:
    'Breakdowns are limited to sanitized routes and bounded product enums. Emails, names, user/distinct ids, document paths, prompts, and tokens are rejected.',
  smallCohorts: `Aggregate groups with fewer than ${MIN_INSIGHT_COHORT_SIZE} users or events are suppressed before interpretation.`,
  embedding:
    'No PostHog iframe or embed is rendered. PostHog embeds require a public sharing token and a CSP frame-src review, so this view links out to the authenticated project instead.',
} as const

export const POSTHOG_INSIGHT_EMBED_POLICY = {
  enabled: false,
  reason:
    'PostHog embeds require a public sharing token and a CSP frame-src review. The admin Analytics tab deliberately links out to the authenticated project instead.',
  cspReviewed: true,
} as const
