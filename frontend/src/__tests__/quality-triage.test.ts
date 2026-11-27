import { describe, expect, it } from 'vitest'
import type { ReplayLinkConfig } from '@/lib/analytics/replay-links'
import {
  buildQualityErrorTrackingUrl,
  buildQualityReplayUrl,
  buildQualityTrendsUrl,
  describeQualityFilters,
  isBlockedQualityRoute,
  normalizeQualityFilters,
  normalizeQualityRelease,
  normalizeQualityRoute,
  QUALITY_ISSUES,
  QUALITY_MIN_COHORT_SIZE,
  QUALITY_ROUTES,
  qualityCountLabel,
  qualityRouteRows,
  qualitySavedInsights,
  qualityTelemetryState,
  suppressQualityCount,
  type QualityIssueDescriptor,
  type QualityTrendsQuery,
} from '@/lib/analytics/quality-triage'

const config: ReplayLinkConfig = { projectId: '756020', days: 30 }

function trendsQuery(href: string): QualityTrendsQuery {
  const url = new URL(href)
  const raw = url.searchParams.get('q')
  expect(raw).toBeTruthy()
  return JSON.parse(raw as string) as QualityTrendsQuery
}

function replayValues(href: string): unknown[] {
  const url = new URL(href)
  const raw = url.searchParams.get('filters')
  expect(raw).toBeTruthy()
  const filters = JSON.parse(raw as string) as {
    filter_group: { values: Array<{ values: unknown[] }> }
  }
  return filters.filter_group.values[0].values
}

const jsError = QUALITY_ISSUES.find((issue) => issue.kind === 'js_error') as QualityIssueDescriptor
const rageClick = QUALITY_ISSUES.find((issue) => issue.kind === 'rage_click') as QualityIssueDescriptor
const deadClick = QUALITY_ISSUES.find((issue) => issue.kind === 'dead_click') as QualityIssueDescriptor

describe('quality saved-insight descriptors', () => {
  it('covers JS errors, rage clicks, and dead clicks with bounded PostHog events', () => {
    expect(QUALITY_ISSUES.map((issue) => issue.kind)).toEqual([
      'js_error',
      'rage_click',
      'dead_click',
    ])
    expect(QUALITY_ISSUES.map((issue) => issue.event)).toEqual([
      '$exception',
      '$rageclick',
      '$dead_click',
    ])
    expect(jsError.errorTypeProperty).toBe('error_type')
    expect(jsError.errorTracking).toBe(true)
    expect(rageClick.errorTypeProperty).toBeNull()
    expect(deadClick.errorTracking).toBe(false)
  })

  it('builds an aggregate trends table filtered by route and release', () => {
    const query = trendsQuery(
      buildQualityTrendsUrl(config, jsError, { route: '/billing', release: 'v1.2.3' }),
    )
    expect(query.kind).toBe('InsightVizNode')
    expect(query.source.kind).toBe('TrendsQuery')
    expect(query.source.dateRange.date_from).toBe('-30d')
    expect(query.source.filterTestAccounts).toBe(true)
    expect(query.source.series[0]).toMatchObject({
      kind: 'EventsNode',
      event: '$exception',
      math: 'total',
    })
    expect(query.source.properties).toEqual([
      { key: 'route', operator: 'exact', type: 'event', value: ['/billing'] },
      { key: '$release_id', operator: 'exact', type: 'event', value: ['v1.2.3'] },
    ])
    expect(query.source.breakdownFilter.breakdowns).toEqual([
      { type: 'event', property: 'route' },
      { type: 'event', property: '$release_id' },
      { type: 'event', property: 'error_type' },
    ])
    expect(query.source.trendsFilter.display).toBe('ActionsTable')
  })

  it('keeps rage and dead-click breakdowns to route and release', () => {
    for (const issue of [rageClick, deadClick]) {
      const query = trendsQuery(
        buildQualityTrendsUrl(config, issue, { route: '/dashboard', release: '2026.11.27' }),
      )
      expect(query.source.breakdownFilter.breakdowns).toEqual([
        { type: 'event', property: 'route' },
        { type: 'event', property: '$release_id' },
      ])
      expect(query.source.properties).toEqual([
        { key: 'route', operator: 'exact', type: 'event', value: ['/dashboard'] },
        { key: '$release_id', operator: 'exact', type: 'event', value: ['2026.11.27'] },
      ])
    }
  })

  it('preserves 7-day ranges and strips untrusted filters', () => {
    const sevenDays = trendsQuery(
      buildQualityTrendsUrl(
        { projectId: '42', days: 7 },
        jsError,
        { route: '/workspace/abc/edit', release: 'person@example.com' },
      ),
    )
    expect(sevenDays.source.dateRange.date_from).toBe('-7d')
    expect(sevenDays.source.properties).toEqual([])
    expect(sevenDays.source.breakdownFilter.breakdowns).toEqual([
      { type: 'event', property: 'route' },
      { type: 'event', property: 'error_type' },
    ])
  })

  it('filters replays by the matching event, sanitized route, and release', () => {
    const href = buildQualityReplayUrl(config, jsError, {
      route: '/billing',
      release: 'v1.2.3',
    })
    expect(href).toContain('/project/756020/replay/home?filters=')
    expect(replayValues(href)).toEqual([
      { id: '$exception', type: 'events', order: 0, name: '$exception' },
      { key: '$current_url', operator: 'icontains', type: 'event', value: '/billing' },
      { key: '$release_id', operator: 'exact', type: 'event', value: ['v1.2.3'] },
    ])
  })

  it('resolves every saved insight and route row against the selected project', () => {
    const saved = qualitySavedInsights(config, { route: '/pricing', release: 'v1' })
    expect(saved).toHaveLength(3)
    for (const insight of saved) {
      expect(insight.trendsHref).toContain('/project/756020/insights/new')
      expect(insight.replayHref).toContain('/project/756020/replay/home')
    }
    expect(saved[0].errorTrackingHref).toBe(
      'https://us.posthog.com/project/756020/error-tracking',
    )
    expect(saved[1].errorTrackingHref).toBeNull()
    expect(saved[0].breakdowns).toEqual(['route', '$release_id', 'error_type'])

    const rows = qualityRouteRows(config, { release: 'v1' })
    expect(rows.map((row) => row.path)).toEqual(QUALITY_ROUTES.map((route) => route.path))
    for (const row of rows) {
      expect(row.savedInsights).toHaveLength(3)
      expect(row.path.startsWith('/')).toBe(true)
      expect(row.path).not.toMatch(/workspace|\/r\/|\/u\/|\/share\/|\/portfolio\/|\/try/)
    }
  })

  it('builds the error tracking destination without a per-user query', () => {
    expect(buildQualityErrorTrackingUrl(config)).toBe(
      'https://us.posthog.com/project/756020/error-tracking',
    )
  })
})

describe('quality route and release sanitization', () => {
  it('allows only sanitized product routes', () => {
    expect(normalizeQualityRoute('/dashboard')).toBe('/dashboard')
    expect(normalizeQualityRoute('/billing')).toBe('/billing')
    expect(normalizeQualityRoute('/login')).toBe('/login')
    for (const blocked of [
      '/workspace/abc/edit',
      '/workspaces/team/recruiter',
      '/try',
      '/r/secret',
      '/u/sanskar',
      '/share/secret',
      '/portfolio/sanskar',
      '/admin',
      '/',
      'https://evil.example/dashboard',
    ]) {
      expect(normalizeQualityRoute(blocked)).toBeNull()
      expect(isBlockedQualityRoute(blocked)).toBe(
        /^\/(?:workspace|workspaces|try|r|u|share|portfolio)(?:\/|$)/i.test(blocked),
      )
    }
  })

  it('accepts bounded releases and rejects identifiers or free text', () => {
    expect(normalizeQualityRelease('v1.2.3')).toBe('v1.2.3')
    expect(normalizeQualityRelease('2026.11.27-abc_1:2')).toBe('2026.11.27-abc_1:2')
    expect(normalizeQualityRelease('a'.repeat(64))).toHaveLength(64)
    for (const blocked of [
      '',
      'person@example.com',
      'release one',
      '/etc/passwd',
      'a'.repeat(65),
      'https://latexy.xyz',
      'release\nvalue',
      'phc_notarealkey123456',
      'Bearer abcdefgh12345678',
      null,
      42,
    ]) {
      expect(normalizeQualityRelease(blocked)).toBeNull()
    }
  })

  it('never sends route tokens, emails, or document paths to PostHog', () => {
    const hrefs = [
      buildQualityTrendsUrl(config, jsError, {
        route: '/workspace/550e8400-e29b-41d4-a716-446655440000/edit',
        release: 'person@example.com',
      }),
      buildQualityReplayUrl(config, deadClick, {
        route: '/r/secret-token',
        release: 'phc_notarealkey123456',
      }),
      ...qualitySavedInsights(config, { route: '/billing', release: 'v1.2.3' }).flatMap(
        (insight) => [insight.trendsHref, insight.replayHref],
      ),
    ]
    for (const href of hrefs) {
      expect(href).not.toMatch(/token|secret|email|phc_|user_id|@/i)
      expect(href).not.toContain('/workspace/')
      expect(href).not.toContain('/r/')
    }
  })

  it('treats unknown filters as all routes and all releases', () => {
    expect(normalizeQualityFilters({ route: '/workspace/x', release: 'a@b.com' })).toEqual({
      route: null,
      release: null,
    })
    expect(describeQualityFilters({ route: '/billing', release: 'v1.2.3' })).toBe(
      'Billing · release v1.2.3',
    )
    expect(describeQualityFilters(null)).toBe('All routes · all releases')
  })
})

describe('quality telemetry status and small-cohort suppression', () => {
  it('labels missing telemetry instead of zero-filling', () => {
    const state = qualityTelemetryState({ configured: false, release: null, days: 7 })
    expect(state.status).toBe('not_configured')
    expect(state.label).toBe('Missing telemetry')
    expect(state.missing).toBe(true)
    expect(state.detail).toContain('not the same as zero errors')
    expect(state.releaseLabel).toBe('Release tag unavailable')
  })

  it('labels a configured project without a release tag honestly', () => {
    const state = qualityTelemetryState({ configured: true, release: null, days: 30 })
    expect(state.status).toBe('available')
    expect(state.missing).toBe(false)
    expect(state.releaseLabel).toBe('Release tag not configured')
    expect(state.suppressionLabel).toContain(String(QUALITY_MIN_COHORT_SIZE))
  })

  it('suppresses 1-4, keeps zero and larger counts, and never invents a missing value', () => {
    expect(suppressQualityCount(3)).toEqual({ value: null, suppressed: true, missing: false })
    expect(suppressQualityCount(4)).toEqual({ value: null, suppressed: true, missing: false })
    expect(suppressQualityCount(5)).toEqual({ value: 5, suppressed: false, missing: false })
    expect(suppressQualityCount(0)).toEqual({ value: 0, suppressed: false, missing: false })
    expect(suppressQualityCount(null)).toEqual({ value: null, suppressed: false, missing: true })
    expect(qualityCountLabel(null)).toBe('Missing telemetry')
    expect(qualityCountLabel(3)).toBe(`Suppressed (<${QUALITY_MIN_COHORT_SIZE})`)
    expect(qualityCountLabel(5)).toBe('5')
    expect(qualityCountLabel(0)).toBe('0')
    expect(qualityCountLabel(1234)).toBe('1,234')
  })
})
