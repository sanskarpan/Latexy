/**
 * Privacy-safe linter telemetry (issue #2148).
 *
 * Only an allowlisted rule id, a bounded severity, a canonical route label, a
 * fixed/applied flag and an issue count leave the browser. LaTeX source, line
 * text, lint messages, document/resume ids and per-user history are never
 * included, even when a caller passes them.
 *
 * The consent gate is shared with the browser analytics boundary: nothing is
 * sent until the visitor grants analytics consent. Events are sampled once per
 * session and deduplicated over a rolling window so repeated lint runs do not
 * inflate rule frequency.
 */

import { readAnalyticsConsent } from '@/lib/analytics/posthog'
import type { LintIssue } from '@/lib/latex-linter'
import { createTraceHeaders } from '@/lib/telemetry'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

export const LINTER_RULE_IDS = [
  'deprecated-bf',
  'deprecated-it',
  'deprecated-rm',
  'deprecated-tt',
  'wrong-quotes',
  'redundant-space',
  'double-dollar',
  'over-command',
  'multicol-ats-risk',
  'fontawesome-ats-risk',
  'tabular-layout',
  'missing-glyphtounicode',
  'hyperref-order',
  'missing-label',
  'duplicate-label',
] as const

export type LinterRuleId = (typeof LINTER_RULE_IDS)[number]
export const LINTER_SEVERITIES = ['error', 'warning', 'info'] as const
export type LinterSeverity = (typeof LINTER_SEVERITIES)[number]

export const LINTER_SAMPLE_RATE_PERCENT = 25
export const LINTER_SAMPLE_STORAGE_KEY = 'latexy-linter-sample'
export const LINTER_DEDUPE_WINDOW_MS = 10 * 60 * 1000

const RULE_ID_SET = new Set<string>(LINTER_RULE_IDS)
const SEVERITY_SET = new Set<string>(LINTER_SEVERITIES)
const STATIC_ROUTES = new Set([
  '/',
  '/try',
  '/templates',
  '/dashboard',
  '/workspace',
  '/workspaces',
  '/login',
  '/signup',
  '/billing',
  '/byok',
  '/settings',
  '/tracker',
])
const ROUTE_PATTERNS: Array<[RegExp, string]> = [
  [/^\/workspace\/[^/]+\/edit\/?$/, '/workspace/:resumeId/edit'],
  [/^\/workspace\/[^/]+\/optimize\/?$/, '/workspace/:resumeId/optimize'],
  [/^\/workspace\/[^/]+\/cover-letter\/?$/, '/workspace/:resumeId/cover-letter'],
  [/^\/workspace\/[^/]+\/career\/?$/, '/workspace/:resumeId/career'],
  [/^\/workspace\/[^/]+\/batch-tailor\/?$/, '/workspace/:resumeId/batch-tailor'],
  [/^\/workspaces\/[^/]+\/recruiter\/?$/, '/workspaces/:workspaceId/recruiter'],
  [/^\/workspaces\/[^/]+\/?$/, '/workspaces/:workspaceId'],
  [/^\/workspace\/[^/]+\/?$/, '/workspace/:resumeId'],
]
const CANONICAL_DYNAMIC_ROUTES = new Set(ROUTE_PATTERNS.map(([, label]) => label))

export interface LinterTelemetryEvent {
  rule_id: LinterRuleId
  severity: LinterSeverity
  route: string
  fixed: boolean
  issue_count: number
}

export interface LinterIssueLike {
  ruleId: string
  severity: string
}

export interface LinterReportOptions {
  fixed: boolean
  route?: string
}

export function sanitizeLinterRoute(pathname: string | null | undefined): string {
  if (!pathname) return '/other'
  const [withoutQuery] = pathname.trim().split('?', 1)
  const route = withoutQuery.split('#', 1)[0].slice(0, 128)
  if (!route.startsWith('/')) return '/other'
  if (STATIC_ROUTES.has(route) || CANONICAL_DYNAMIC_ROUTES.has(route)) return route
  for (const [pattern, label] of ROUTE_PATTERNS) {
    if (pattern.test(route)) return label
  }
  return '/other'
}

/**
 * Aggregate lint issues by rule+severity and keep only allowlisted values.
 * Counts, never issue text or positions, are the only thing retained.
 */
export function buildLinterTelemetryEvents(
  issues: readonly LinterIssueLike[],
  options: LinterReportOptions,
): LinterTelemetryEvent[] {
  const route = sanitizeLinterRoute(options.route)
  const counts = new Map<string, LinterTelemetryEvent>()
  for (const issue of issues) {
    if (!RULE_ID_SET.has(issue.ruleId) || !SEVERITY_SET.has(issue.severity)) continue
    const key = `${issue.ruleId}:${issue.severity}`
    const existing = counts.get(key)
    if (existing) {
      existing.issue_count = Math.min(10_000, existing.issue_count + 1)
      continue
    }
    counts.set(key, {
      rule_id: issue.ruleId as LinterRuleId,
      severity: issue.severity as LinterSeverity,
      route,
      fixed: options.fixed,
      issue_count: 1,
    })
  }
  return [...counts.values()].sort(
    (left, right) =>
      left.rule_id.localeCompare(right.rule_id) || left.severity.localeCompare(right.severity),
  )
}

function sessionSampleBucket(storage: Storage | null, random: () => number): number {
  try {
    const stored = storage?.getItem(LINTER_SAMPLE_STORAGE_KEY)
    const parsed = stored ? Number.parseInt(stored, 10) : Number.NaN
    if (Number.isInteger(parsed) && parsed >= 1 && parsed <= 100) return parsed
  } catch {
    // Storage can be unavailable in hardened/private contexts.
  }
  const bucket = Math.min(100, Math.max(1, Math.floor(random() * 100) + 1))
  try {
    storage?.setItem(LINTER_SAMPLE_STORAGE_KEY, String(bucket))
  } catch {
    // The in-memory decision still applies for this page.
  }
  return bucket
}

export interface LinterTelemetryClientOptions {
  readConsent: () => 'granted' | 'denied' | null
  getStorage: () => Storage | null
  now: () => number
  random: () => number
  send: (events: LinterTelemetryEvent[]) => void
}

export interface LinterTelemetryClient {
  report: (issues: readonly LinterIssueLike[], options: LinterReportOptions) => boolean
  reset: () => void
}

export function createLinterTelemetryClient(
  options: LinterTelemetryClientOptions,
): LinterTelemetryClient {
  const sentAt = new Map<string, number>()

  function report(issues: readonly LinterIssueLike[], reportOptions: LinterReportOptions): boolean {
    if (options.readConsent() !== 'granted') return false
    const events = buildLinterTelemetryEvents(issues, reportOptions)
    if (events.length === 0) return false

    const sampled = sessionSampleBucket(options.getStorage(), options.random) <= LINTER_SAMPLE_RATE_PERCENT
    if (!sampled) return false

    const timestamp = options.now()
    const fresh = events.filter((event) => {
      const key = `${event.rule_id}:${event.severity}:${event.route}:${event.fixed}:${event.issue_count}`
      const previous = sentAt.get(key)
      return previous === undefined || timestamp - previous >= LINTER_DEDUPE_WINDOW_MS
    })
    if (fresh.length === 0) return false

    for (const event of fresh) {
      const key = `${event.rule_id}:${event.severity}:${event.route}:${event.fixed}:${event.issue_count}`
      sentAt.set(key, timestamp)
    }
    options.send(fresh)
    return true
  }

  return {
    report,
    reset: () => sentAt.clear(),
  }
}

function browserStorage(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.sessionStorage ?? null
  } catch {
    return null
  }
}

function sendLinterTelemetry(events: LinterTelemetryEvent[]): void {
  const body = JSON.stringify({ events })
  try {
    void fetch(`${API_BASE}/telemetry/linter`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...createTraceHeaders(),
      },
      body,
      credentials: 'include',
      keepalive: true,
    }).catch(() => undefined)
  } catch {
    // Telemetry must never break the editor.
  }
}

export const linterTelemetry = createLinterTelemetryClient({
  readConsent: readAnalyticsConsent,
  getStorage: browserStorage,
  now: () => Date.now(),
  random: Math.random,
  send: sendLinterTelemetry,
})

/** Report the rules currently visible in one completed lint run. */
export function reportLinterIssues(
  issues: readonly LintIssue[] | readonly LinterIssueLike[],
  options: LinterReportOptions = { fixed: false },
): boolean {
  const route =
    options.route ??
    (typeof window === 'undefined' ? '/other' : sanitizeLinterRoute(window.location.pathname))
  return linterTelemetry.report(issues, { ...options, route })
}
