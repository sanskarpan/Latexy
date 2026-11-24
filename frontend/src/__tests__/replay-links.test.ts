import { describe, expect, it } from 'vitest'
import {
  buildReplayUrl,
  checkoutFailureReplayUrl,
  DEFAULT_POSTHOG_UI_HOST,
  jsErrorReplayUrl,
  LONG_SESSION_MIN_ACTIVE_SECONDS,
  longSessionReplayUrl,
  planReplayUrl,
  REPLAY_TRIAGE_PLANS,
  REPLAY_TRIAGE_ROUTES,
  replayTriageLinks,
  routeReplayUrl,
  type ReplayLinkConfig,
  type ReplayUniversalFilter,
} from '@/lib/analytics/replay-links'

const config: ReplayLinkConfig = { projectId: '756020', days: 30 }

function parseFilters(url: string): Record<string, unknown> {
  const parsed = new URL(url)
  const raw = parsed.searchParams.get('filters')
  expect(raw).toBeTruthy()
  return JSON.parse(raw as string) as Record<string, unknown>
}

function groupValues(url: string): unknown[] {
  const filters = parseFilters(url)
  const group = filters.filter_group as { values: Array<{ values: unknown[] }> }
  return group.values[0].values
}

describe('replay triage URL builder', () => {
  it('targets the configured project and replay home', () => {
    const url = checkoutFailureReplayUrl(config)
    expect(url).toContain(`/project/756020/replay/home`)
    expect(url).toContain('?filters=')
  })

  it('defaults to the US PostHog app host and strips trailing slashes', () => {
    expect(checkoutFailureReplayUrl({ projectId: '756020', days: 7 })).toContain(`${DEFAULT_POSTHOG_UI_HOST}/project/`)
    expect(
      checkoutFailureReplayUrl({ projectId: '756020', uiHost: 'https://eu.posthog.com/', days: 7 }),
    ).toContain('https://eu.posthog.com/project/756020')
  })

  it('preserves the selected date range as a relative date_from', () => {
    expect(parseFilters(checkoutFailureReplayUrl({ projectId: '756020', days: 7 })).date_from).toBe('-7d')
    expect(parseFilters(checkoutFailureReplayUrl({ projectId: '756020', days: 30 })).date_from).toBe('-30d')
    expect(parseFilters(checkoutFailureReplayUrl({ projectId: '756020', days: 90 })).date_from).toBe('-90d')
  })

  it('filters checkout failures by the checkout_failed event', () => {
    expect(groupValues(checkoutFailureReplayUrl(config))).toEqual([
      { id: 'checkout_failed', type: 'events', order: 0, name: 'checkout_failed' },
    ])
  })

  it('filters JS errors by console error level', () => {
    expect(groupValues(jsErrorReplayUrl(config))).toEqual([
      { key: 'level', operator: 'exact', type: 'log_entry', value: ['error'] },
    ])
  })

  it('filters routes by the sanitized $current_url', () => {
    expect(groupValues(routeReplayUrl(config, '/billing'))).toEqual([
      { key: '$current_url', operator: 'icontains', type: 'event', value: '/billing' },
    ])
  })

  it('filters plans by the person plan property', () => {
    expect(groupValues(planReplayUrl(config, 'pro'))).toEqual([
      { key: 'plan', operator: 'exact', type: 'person', value: ['pro'] },
    ])
  })

  it('filters long sessions by active seconds', () => {
    const filters = parseFilters(longSessionReplayUrl(config))
    expect(filters.duration).toEqual([
      { key: 'active_seconds', operator: 'gt', type: 'recording', value: LONG_SESSION_MIN_ACTIVE_SECONDS },
    ])
    expect(groupValues(longSessionReplayUrl(config))).toEqual([])
  })

  it('lets a caller raise the long-session threshold', () => {
    const filters = parseFilters(longSessionReplayUrl(config, 600))
    expect(filters.duration).toEqual([{ key: 'active_seconds', operator: 'gt', type: 'recording', value: 600 }])
  })

  it('returns every triage link grouped by kind', () => {
    const links = replayTriageLinks(config)
    expect(links.checkoutFailures).toContain('?filters=')
    expect(links.jsErrors).toContain('?filters=')
    expect(links.longSessions).toContain('?filters=')
    expect(links.routes.map((r) => r.label)).toEqual(REPLAY_TRIAGE_ROUTES.map((r) => r.label))
    expect(links.plans.map((p) => p.label)).toEqual(REPLAY_TRIAGE_PLANS.map((p) => p.label))
  })

  it('keeps every triage link on the configured project and date range', () => {
    const links = replayTriageLinks({ projectId: '42', days: 90 })
    const all = [
      links.checkoutFailures,
      links.jsErrors,
      links.longSessions,
      ...links.routes.map((r) => r.href),
      ...links.plans.map((p) => p.href),
    ]
    for (const href of all) {
      expect(href.startsWith(`${DEFAULT_POSTHOG_UI_HOST}/project/42/replay/home?filters=`)).toBe(true)
      expect(parseFilters(href).date_from).toBe('-90d')
    }
  })

  it('keeps only templated routes and low-cardinality plan enums', () => {
    const links = replayTriageLinks(config)
    const all = [
      links.checkoutFailures,
      links.jsErrors,
      links.longSessions,
      ...links.routes.map((r) => r.href),
      ...links.plans.map((p) => p.href),
    ]
    for (const href of all) {
      // A triage URL must never carry a project token, an email, or an
      // identifier-bearing document route.
      expect(href).not.toMatch(/token|secret|email|phc_/i)
      expect(href).not.toContain('@')
      expect(href).not.toContain('/u/')
      expect(href).not.toContain('/r/')
      expect(href).not.toContain('/share/')
    }
    // The editor route is the templated form, never a real résumé id.
    const routeValue = groupValues(links.routes[0].href)[0] as { value: string }
    expect(routeValue.value).toBe('/workspace/:resumeId/edit')
  })

  it('builds a deterministic URL for arbitrary filters', () => {
    const override: Partial<ReplayUniversalFilter> = {
      filter_group: { type: 'AND', values: [{ type: 'AND', values: [{ id: 'x', type: 'events', order: 0, name: 'x' }] }] },
    }
    expect(buildReplayUrl(config, override)).toBe(buildReplayUrl(config, override))
  })
})
