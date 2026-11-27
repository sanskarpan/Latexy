import { readFileSync } from 'node:fs'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import AdminErrorFeed from '@/components/admin/AdminErrorFeed'
import type { AdminErrorFeedResponse } from '@/lib/api-client'
import { buildClientErrorSignal } from '@/lib/analytics/error-signals'
import type { ReplayLinkConfig } from '@/lib/analytics/replay-links'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
const config: ReplayLinkConfig = { projectId: '756020', days: 7 }

const feed: AdminErrorFeedResponse = {
  generated_at: '2026-11-27T10:00:00+00:00',
  days: 7,
  window: { start: '2026-11-20T10:00:00+00:00', end: '2026-11-27T10:00:00+00:00' },
  filters: { source: null, route: null, error_class: null },
  threshold: { occurrences: 10, window_minutes: 15, cooldown_minutes: 60 },
  groups: [
    {
      id: 'group-1',
      source: 'frontend',
      route: '/dashboard',
      release: 'v1.2.3',
      error_class: 'TypeError',
      occurrence_count: 42,
      window_events: 12,
      window_started_at: '2026-11-27T09:50:00+00:00',
      first_seen_at: '2026-11-26T09:00:00+00:00',
      last_seen_at: '2026-11-27T09:59:00+00:00',
      last_alerted_at: '2026-11-27T09:45:00+00:00',
      alert_count: 2,
    },
  ],
  totals: {
    events: 42,
    groups: 2,
    visible_groups: 1,
    routes: 1,
    releases: 1,
    suppressed_groups: 1,
    suppressed_events: 3,
  },
  suppression: {
    minimum_cohort_size: 5,
    user_dimension_included: false,
    messages_included: false,
  },
  delivery: { configured: true, channels: ['slack', 'email'] },
  runbook_url:
    'https://github.com/sanskarpan/Latexy/blob/main/docs/observability/error-alert-runbook.md',
}

describe('admin error feed surface', () => {
  const page = read('../app/admin/page.tsx')
  const component = read('../components/admin/AdminErrorFeed.tsx')
  const signals = read('../lib/analytics/error-signals.ts')
  const posthog = read('../lib/analytics/posthog.ts')

  it('is wired into the existing Quality tab rather than a new surface', () => {
    expect(page).toContain(
      "import AdminErrorFeed from '@/components/admin/AdminErrorFeed'",
    )
    expect(page).toContain('<AdminQualityTriage />')
    expect(page).toContain('<AdminErrorFeed />')
    expect(page).toContain("{ id: 'quality', label: 'Quality' }")
  })

  it('renders grouped errors, suppression, delivery state and runbook', () => {
    const html = renderToStaticMarkup(
      createElement(AdminErrorFeed, { configOverride: config, feedOverride: feed }),
    )
    expect(html).toContain('Error feed')
    expect(html).toContain('TypeError')
    expect(html).toContain('/dashboard')
    expect(html).toContain('v1.2.3')
    expect(html).toContain('slack, email')
    expect(html).toContain('suppressed')
    expect(html).toContain('No per-user rows')
    expect(html).toContain('Replay')
    expect(html).toContain('Error tracking')
    expect(html).toContain('/error-tracking?search=')
    expect(html).toContain('Open the error alert runbook')
    expect(html).not.toContain('user_id')
    expect(html).not.toContain('distinct_id')
  })

  it('labels missing PostHog telemetry instead of rendering broken links', () => {
    const html = renderToStaticMarkup(
      createElement(AdminErrorFeed, { configOverride: null, feedOverride: feed }),
    )
    expect(html).toContain('Missing telemetry')
    expect(html).not.toContain('/project/756020')
  })

  it('keeps the component aggregate-only', () => {
    expect(component).toContain('buildQualityErrorGroupReplayUrl')
    expect(component).toContain('buildQualityErrorGroupErrorTrackingUrl')
    expect(component).toContain('Masked replay only')
    expect(component).toContain('suppression.minimum_cohort_size')
    expect(component).toContain('evaluateAdminErrorAlerts')
    expect(component).not.toContain('user_id')
    expect(component).not.toContain('distinct_id')
    expect(component).not.toContain('latex_content')
  })

  it('mirrors only the sanitized exception identity after the consent gate', () => {
    expect(posthog).toContain('reportClientErrorSignal(sanitized)')
    expect(signals).toContain("'latexy-analytics-consent'")
    expect(signals).toContain('/telemetry/errors')
    expect(signals).toContain("event.event !== '$exception'")

    const signal = buildClientErrorSignal({
      event: '$exception',
      properties: {
        route: '/billing',
        $release_id: 'v1.2.3',
        error_type: 'TypeError',
        $exception_message: 'private document text',
        email: 'user@example.com',
        token: 'sk-live-secret',
      },
    })
    expect(signal).toEqual({ error_class: 'TypeError', route: '/billing', release: 'v1.2.3' })

    expect(
      buildClientErrorSignal({
        event: '$exception',
        properties: { route: '/workspace/abc', error_type: 'TypeError' },
      }),
    ).toBeNull()
    expect(
      buildClientErrorSignal({ event: '$pageview', properties: { route: '/billing' } }),
    ).toBeNull()
  })
})
