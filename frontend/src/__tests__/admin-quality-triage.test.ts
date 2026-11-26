import { readFileSync } from 'node:fs'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import AdminQualityTriage from '@/components/admin/AdminQualityTriage'
import type { ReplayLinkConfig } from '@/lib/analytics/replay-links'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
const config: ReplayLinkConfig = { projectId: '756020', days: 30 }

describe('admin quality triage surface', () => {
  const page = read('../app/admin/page.tsx')
  const component = read('../components/admin/AdminQualityTriage.tsx')
  const quality = read('../lib/analytics/quality-triage.ts')
  const posthog = read('../lib/analytics/posthog.ts')
  const docs = read('../../../docs/POSTHOG.md')

  it('is wired as an admin-only Quality tab', () => {
    expect(page).toContain(
      "import AdminQualityTriage from '@/components/admin/AdminQualityTriage'",
    )
    expect(page).toContain("{ id: 'quality', label: 'Quality' }")
    expect(page).toContain('<AdminQualityTriage />')
    expect(page).toContain("tab === 'quality' && <AdminTemplatePerformance />")
    expect(page).not.toContain("SUPPORT_TABS: Array<{ id: TabId; label: string }> = [\n  { id: 'quality'")
  })

  it('renders missing telemetry explicitly and never zero-fills it', () => {
    const html = renderToStaticMarkup(
      createElement(AdminQualityTriage, { configOverride: null }),
    )
    expect(html).toContain('Quality triage')
    expect(html).toContain('Missing telemetry')
    expect(html).toContain('not the same as zero errors')
    expect(html).toContain('JavaScript errors')
    expect(html).toContain('Rage clicks')
    expect(html).toContain('Dead clicks')
    expect(html).not.toContain('0 errors')
    expect(html).not.toContain('0 dead clicks')
    expect(html).not.toContain('https://us.posthog.com/project/756020')
  })

  it('renders filtered trends and replay links when PostHog is configured', () => {
    const html = renderToStaticMarkup(
      createElement(AdminQualityTriage, {
        configOverride: config,
        releaseOverride: 'v1.2.3',
      }),
    )
    expect(html).toContain('PostHog telemetry linked')
    expect(html).toContain('Release v1.2.3')
    expect(html).toContain('https://us.posthog.com/project/756020/insights/new')
    expect(html).toContain('https://us.posthog.com/project/756020/replay/home')
    expect(html).toContain('error-tracking')
    expect(html).toContain('$exception')
    expect(html).toContain('$rageclick')
    expect(html).toContain('$dead_click')
    expect(html).toContain('No per-user rows')
    expect(html).toContain('suppressed')
    expect(html).not.toContain('/workspace/')
    expect(html).not.toContain('/r/')
  })

  it('keeps the descriptors aggregate-only and the small-cohort policy explicit', () => {
    expect(component).toContain('QUALITY_ISSUES')
    expect(component).toContain('buildQualityTrendsUrl')
    expect(component).toContain('buildQualityReplayUrl')
    expect(component).toContain('QUALITY_MIN_COHORT_SIZE')
    expect(component).toContain('No per-user rows')
    expect(component).not.toContain('user_id')
    expect(component).not.toContain('latex_content')
    expect(component).not.toContain('email')
    expect(quality).toContain('$exception')
    expect(quality).toContain('$rageclick')
    expect(quality).toContain('$dead_click')
    expect(quality).toContain('QUALITY_MIN_COHORT_SIZE')
    expect(quality).toContain('Missing telemetry')
    expect(quality).toContain('error_type')
    expect(quality).not.toContain('user_id')
    expect(quality).not.toContain('distinct_id')
  })

  it('enables exception and dead-click capture behind the consent gate', () => {
    expect(posthog).toContain('capture_exceptions: true')
    expect(posthog).toContain('capture_dead_clicks: true')
    expect(posthog).toContain('capture_pageleave: false')
    expect(posthog).toContain('mask_all_text: true')
    expect(posthog).toContain("maskTextSelector: '*'")
    expect(posthog).toContain('isBlockedAnalyticsPath')
    expect(posthog).toContain('sanitizeAnalyticsEvent')
    expect(posthog).toContain('sanitizeExceptionText')
    expect(posthog).toContain('NEXT_PUBLIC_APP_RELEASE')
    expect(posthog).toContain('startExceptionAutocapture()')
    expect(posthog).toContain('stopExceptionAutocapture()')
    expect(posthog).toContain("readAnalyticsConsent() !== 'granted'")
    expect(posthog).toContain('disable_session_recording: true')
    expect(posthog).not.toContain('mask_all_text: false')
  })

  it('documents the release tag, data boundary, and missing-telemetry rule', () => {
    expect(docs).toContain('NEXT_PUBLIC_APP_RELEASE')
    expect(docs).toContain('capture_exceptions: true')
    expect(docs).toContain('$dead_click')
    expect(docs).toContain('Missing telemetry')
    expect(docs).toContain('fewer than five')
    expect(docs).toContain('no unmask switch')
  })
})
