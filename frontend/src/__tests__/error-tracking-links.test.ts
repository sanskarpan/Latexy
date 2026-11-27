import { describe, expect, it } from 'vitest'
import type { ReplayLinkConfig } from '@/lib/analytics/replay-links'
import {
  buildQualityErrorGroupErrorTrackingUrl,
  buildQualityErrorGroupReplayUrl,
  normalizeQualityErrorClass,
} from '@/lib/analytics/quality-triage'

const config: ReplayLinkConfig = { projectId: '756020', days: 7 }

function replayFilters(href: string): unknown[] {
  const url = new URL(href)
  const raw = url.searchParams.get('filters')
  expect(raw).toBeTruthy()
  const filters = JSON.parse(raw as string) as {
    filter_group: { values: Array<{ values: unknown[] }> }
  }
  return filters.filter_group.values[0].values
}

describe('error group PostHog links', () => {
  const group = {
    source: 'frontend' as const,
    route: '/dashboard',
    release: 'v1.2.3',
    error_class: 'TypeError',
  }

  it('builds an aggregate replay link filtered by exception, route, release and class', () => {
    const values = replayFilters(buildQualityErrorGroupReplayUrl(config, group))
    expect(values).toContainEqual({
      id: '$exception',
      type: 'events',
      order: 0,
      name: '$exception',
    })
    expect(values).toContainEqual({
      key: '$current_url',
      operator: 'icontains',
      type: 'event',
      value: '/dashboard',
    })
    expect(values).toContainEqual({
      key: '$release_id',
      operator: 'exact',
      type: 'event',
      value: ['v1.2.3'],
    })
    expect(values).toContainEqual({
      key: 'error_type',
      operator: 'exact',
      type: 'event',
      value: ['TypeError'],
    })
  })

  it('builds an error-tracking link with only bounded search terms', () => {
    const href = buildQualityErrorGroupErrorTrackingUrl(config, group)
    const url = new URL(href)
    expect(url.pathname).toBe('/project/756020/error-tracking')
    expect(url.searchParams.get('search')).toBe('TypeError /dashboard v1.2.3')
  })

  it('drops document routes, emails, tokens and free-form text from links', () => {
    const unsafe = {
      source: 'frontend' as const,
      route: '/workspace/3f0c3a5e-1f0a-4d1b-9a53-5d2a9b1c7e11',
      release: 'sk-live-secret-token',
      error_class: 'boom: user@example.com',
    }
    const rendered = `${buildQualityErrorGroupReplayUrl(config, unsafe)} ${buildQualityErrorGroupErrorTrackingUrl(
      config,
      unsafe,
    )}`
    expect(rendered).not.toContain('workspace')
    expect(rendered).not.toContain('sk-live')
    expect(rendered).not.toContain('example.com')
    expect(rendered).not.toContain('boom')
    expect(rendered).toContain('/replay/home')
    expect(rendered).toContain('/error-tracking')
  })

  it('exposes a bounded class normalizer', () => {
    expect(normalizeQualityErrorClass('RangeError')).toBe('RangeError')
    expect(normalizeQualityErrorClass('ValueError: private text')).toBeNull()
    expect(normalizeQualityErrorClass(42)).toBeNull()
  })
})
