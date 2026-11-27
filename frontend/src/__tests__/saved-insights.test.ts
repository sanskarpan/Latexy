import { describe, expect, it } from 'vitest'
import type { SavedInsightLinkConfig } from '@/lib/analytics/saved-insights'
import {
  boundedInsightDays,
  buildDraftSavedInsightUrl,
  buildSavedInsightQuery,
  buildSavedInsightUrl,
  insightCountLabel,
  isSafeInsightBreakdown,
  MIN_INSIGHT_COHORT_SIZE,
  normalizeSavedInsightId,
  POSTHOG_INSIGHT_EMBED_POLICY,
  POSTHOG_INSIGHT_RANGES,
  resolveSavedInsight,
  resolveSavedInsightCatalog,
  SAVED_INSIGHT_CATALOG,
  savedInsightCatalogState,
  suppressInsightCount,
  type SavedInsightDescriptor,
  type SavedInsightQuery,
} from '@/lib/analytics/saved-insights'

const config: SavedInsightLinkConfig = { projectId: '756020', days: 30 }

function draftQuery(href: string): SavedInsightQuery {
  const url = new URL(href)
  const raw = url.searchParams.get('q')
  expect(raw).toBeTruthy()
  return JSON.parse(raw as string) as SavedInsightQuery
}

function descriptor(kind: SavedInsightDescriptor['kind']): SavedInsightDescriptor {
  const found = SAVED_INSIGHT_CATALOG.find((item) => item.kind === kind)
  if (!found) throw new Error(`Missing saved insight descriptor: ${kind}`)
  return found
}

describe('saved insight descriptor catalog', () => {
  it('covers funnels, trends, paths, retention, and stickiness', () => {
    expect(SAVED_INSIGHT_CATALOG.map((item) => item.kind)).toEqual([
      'funnel',
      'trends',
      'paths',
      'retention',
      'stickiness',
    ])
    expect(SAVED_INSIGHT_CATALOG.map((item) => item.insightType)).toEqual([
      'FUNNELS',
      'TRENDS',
      'PATHS',
      'RETENTION',
      'STICKINESS',
    ])
    for (const item of SAVED_INSIGHT_CATALOG) {
      expect(item.events.length).toBeGreaterThan(0)
      expect(item.minimumCohortSize).toBe(MIN_INSIGHT_COHORT_SIZE)
      expect(item.savedInsightEnvVar).toMatch(/^NEXT_PUBLIC_POSTHOG_INSIGHT_[A-Z]+_ID$/)
    }
    expect(POSTHOG_INSIGHT_RANGES).toEqual([7, 30, 90])
  })

  it('builds a typed aggregate query for every descriptor', () => {
    const funnel = draftQuery(buildDraftSavedInsightUrl(config, descriptor('funnel')))
    expect(funnel.kind).toBe('InsightVizNode')
    expect(funnel.source.kind).toBe('FunnelsQuery')
    if (funnel.source.kind !== 'FunnelsQuery') throw new Error('unexpected query')
    expect(funnel.source.dateRange).toEqual({ date_from: '-30d', date_to: null })
    expect(funnel.source.filterTestAccounts).toBe(true)
    expect(funnel.source.series.map((step) => step.event)).toEqual([
      '$pageview',
      'product_event',
      'compilation_tracked',
      'checkout_started',
    ])
    expect(funnel.source.funnelsFilter.funnelVizType).toBe('steps')

    const trends = draftQuery(buildDraftSavedInsightUrl(config, descriptor('trends')))
    if (trends.source.kind !== 'TrendsQuery') throw new Error('unexpected query')
    expect(trends.source.interval).toBe('day')
    expect(trends.source.breakdownFilter).toEqual({
      breakdown_type: 'event',
      breakdowns: [{ type: 'event', property: 'route' }],
      breakdown_limit: 25,
    })
    expect(trends.source.trendsFilter.display).toBe('ActionsTable')

    const paths = draftQuery(buildDraftSavedInsightUrl(config, descriptor('paths')))
    if (paths.source.kind !== 'PathsQuery') throw new Error('unexpected query')
    expect(paths.source.pathsFilter).toEqual({
      includeEventTypes: ['$pageview'],
      startPoint: '/dashboard',
      pathGrouping: 'path',
      edgeLimit: 50,
    })

    const retention = draftQuery(buildDraftSavedInsightUrl(config, descriptor('retention')))
    if (retention.source.kind !== 'RetentionQuery') throw new Error('unexpected query')
    expect(retention.source.retentionFilter.period).toBe('Week')
    expect(retention.source.retentionFilter.totalIntervals).toBe(8)
    expect(retention.source.retentionFilter.targetEntity).toMatchObject({
      id: 'compilation_tracked',
      type: 'events',
    })

    const stickiness = draftQuery(buildDraftSavedInsightUrl(config, descriptor('stickiness')))
    if (stickiness.source.kind !== 'StickinessQuery') throw new Error('unexpected query')
    expect(stickiness.source.series[0].event).toBe('feature_used')
    expect(stickiness.source.breakdownFilter?.breakdowns).toEqual([
      { type: 'event', property: 'feature' },
    ])
    expect(stickiness.source.stickinessFilter.computedAs).toBe('dau')
  })

  it('preserves the selected 7/30/90-day range in draft queries', () => {
    for (const days of POSTHOG_INSIGHT_RANGES) {
      const query = draftQuery(
        buildDraftSavedInsightUrl({ projectId: '42', days }, descriptor('trends')),
      )
      expect(query.source.dateRange.date_from).toBe(`-${days}d`)
      expect(query.source.dateRange.date_to).toBeNull()
    }
  })

  it('links saved ids with the project and a date-range override', () => {
    const savedConfig: SavedInsightLinkConfig = {
      ...config,
      savedInsightIds: { funnel: 'abc12345', retention: 'retain_1' },
    }
    const funnel = resolveSavedInsight(savedConfig, descriptor('funnel'))
    expect(funnel.mode).toBe('saved')
    expect(funnel.href).toContain('/project/756020/insights/abc12345?filters_override=')
    const override = JSON.parse(
      new URL(funnel.href).searchParams.get('filters_override') as string,
    ) as { date_from: string; date_to: null }
    expect(override).toEqual({ date_from: '-30d', date_to: null })
    expect(funnel.draftHref).toContain('/project/756020/insights/new?insight=FUNNELS')

    const retention = resolveSavedInsight(savedConfig, descriptor('retention'))
    expect(retention.mode).toBe('saved')
    expect(retention.href).toContain('/insights/retain_1')

    const trends = resolveSavedInsight(savedConfig, descriptor('trends'))
    expect(trends.mode).toBe('draft')
    expect(trends.savedHref).toBeNull()
    expect(trends.href).toBe(trends.draftHref)
  })

  it('rejects unsafe saved ids and falls back to the prefilled draft', () => {
    const savedConfig: SavedInsightLinkConfig = {
      ...config,
      savedInsightIds: {
        funnel: '../../evil',
        trends: 'person@example.com',
        paths: 'a'.repeat(65),
        retention: 'phc_notakey123',
        stickiness: 'valid_id-1',
      },
    }
    for (const kind of ['funnel', 'trends', 'paths', 'retention'] as const) {
      const resolved = resolveSavedInsight(savedConfig, descriptor(kind))
      expect(resolved.savedHref).toBeNull()
      expect(resolved.mode).toBe('draft')
      expect(resolved.href).toContain('/insights/new?insight=')
    }
    expect(resolveSavedInsight(savedConfig, descriptor('stickiness')).mode).toBe('saved')
  })

  it('normalizes hosts and rejects unbounded ids', () => {
    expect(normalizeSavedInsightId('abc12345')).toBe('abc12345')
    expect(normalizeSavedInsightId('valid_id-1')).toBe('valid_id-1')
    for (const value of [
      '',
      'a/b',
      '..',
      'has space',
      'a'.repeat(65),
      'phc_notakey123',
      'Bearer abcdefgh12345678',
      null,
      42,
    ]) {
      expect(normalizeSavedInsightId(value)).toBeNull()
    }
    expect(
      buildDraftSavedInsightUrl(
        { projectId: '756020', uiHost: 'https://eu.posthog.com/', days: 7 },
        descriptor('funnel'),
      ),
    ).toContain('https://eu.posthog.com/project/756020/insights/new?insight=FUNNELS')
    expect(
      buildDraftSavedInsightUrl(
        { projectId: '756020', uiHost: 'javascript:alert(1)', days: 7 },
        descriptor('funnel'),
      ),
    ).toContain('https://us.posthog.com/project/756020/insights/new?insight=FUNNELS')
    expect(buildSavedInsightUrl(config, descriptor('funnel'), null)).toBeNull()
  })

  it('bounds arbitrary ranges without losing the selected default', () => {
    expect(boundedInsightDays(Number.NaN)).toBe(30)
    expect(boundedInsightDays(0)).toBe(1)
    expect(boundedInsightDays(-10)).toBe(1)
    expect(boundedInsightDays(7.6)).toBe(8)
    expect(boundedInsightDays(999)).toBe(365)
    expect(buildSavedInsightQuery(descriptor('funnel'), 90).source.dateRange.date_from).toBe('-90d')
  })
})

describe('saved insight privacy boundaries', () => {
  it('allows only low-cardinality breakdowns and rejects PII', () => {
    for (const item of SAVED_INSIGHT_CATALOG) {
      for (const breakdown of item.breakdowns) {
        expect(isSafeInsightBreakdown(breakdown)).toBe(true)
      }
    }
    expect(isSafeInsightBreakdown('route')).toBe(true)
    expect(isSafeInsightBreakdown('feature')).toBe(true)
    expect(isSafeInsightBreakdown('$release_id')).toBe(true)
    for (const blocked of [
      'email',
      'user_id',
      'distinct_id',
      'person',
      'name',
      'resume_content',
      'latex',
      'prompt',
      'token',
      'ip',
      '$current_url',
    ]) {
      expect(isSafeInsightBreakdown(blocked)).toBe(false)
    }
  })

  it('never embeds PII or tokens in any generated URL', () => {
    const resolved = resolveSavedInsightCatalog({
      ...config,
      savedInsightIds: {
        funnel: 'abc123',
        trends: 'def456',
        paths: 'ghi789',
        retention: 'jkl012',
        stickiness: 'mno345',
      },
    })
    for (const insight of resolved) {
      for (const href of [insight.href, insight.draftHref]) {
        expect(href).not.toMatch(/@|email|secret|token|user_id|distinct_id|person_id|workspace|\/r\//i)
        expect(href).toContain('/project/756020/')
      }
      expect(insight.breakdowns.every(isSafeInsightBreakdown)).toBe(true)
    }
  })

  it('states the no-embed and no-public-sharing policy', () => {
    expect(POSTHOG_INSIGHT_EMBED_POLICY.enabled).toBe(false)
    expect(POSTHOG_INSIGHT_EMBED_POLICY.cspReviewed).toBe(true)
    expect(POSTHOG_INSIGHT_EMBED_POLICY.reason).toMatch(/public sharing token/i)
  })

  it('suppresses 1-4, keeps zero and larger counts, and never invents missing data', () => {
    expect(suppressInsightCount(3)).toEqual({ value: null, suppressed: true, missing: false })
    expect(suppressInsightCount(4)).toEqual({ value: null, suppressed: true, missing: false })
    expect(suppressInsightCount(5)).toEqual({ value: 5, suppressed: false, missing: false })
    expect(suppressInsightCount(0)).toEqual({ value: 0, suppressed: false, missing: false })
    expect(suppressInsightCount(null)).toEqual({ value: null, suppressed: false, missing: true })
    expect(suppressInsightCount(-1)).toEqual({ value: null, suppressed: false, missing: true })
    expect(insightCountLabel(null)).toBe('Missing telemetry')
    expect(insightCountLabel(3)).toBe(`Suppressed (<${MIN_INSIGHT_COHORT_SIZE})`)
    expect(insightCountLabel(5)).toBe('5')
    expect(insightCountLabel(1234)).toBe('1,234')
  })
})

describe('saved insight fallback state', () => {
  it('labels a missing project and keeps first-party KPIs independent', () => {
    const state = savedInsightCatalogState({ config: null, days: 30 })
    expect(state.status).toBe('not_configured')
    expect(state.configured).toBe(false)
    expect(state.label).toBe('PostHog not configured')
    expect(state.detail).toMatch(/first-party KPI cards/i)
    expect(state.fallbackLabel).toBe('First-party KPIs unaffected')
    expect(state.savedCount).toBe(0)
    expect(state.draftCount).toBe(0)
    expect(state.cohortLabel).toContain(String(MIN_INSIGHT_COHORT_SIZE))
  })

  it('counts saved and draft descriptors without hiding the catalog', () => {
    const drafts = savedInsightCatalogState({ config, days: 30 })
    expect(drafts.configured).toBe(true)
    expect(drafts.savedCount).toBe(0)
    expect(drafts.draftCount).toBe(SAVED_INSIGHT_CATALOG.length)

    const saved = savedInsightCatalogState({
      config: { ...config, savedInsightIds: { funnel: 'abc123', stickiness: 'sticky1' } },
      days: 7,
    })
    expect(saved.savedCount).toBe(2)
    expect(saved.draftCount).toBe(SAVED_INSIGHT_CATALOG.length - 2)
    expect(saved.days).toBe(7)
  })
})
