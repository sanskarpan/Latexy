import { readFileSync } from 'node:fs'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import AdminPostHogInsights from '@/components/admin/AdminPostHogInsights'
import { analyticsSavedInsightConfig } from '@/lib/analytics/posthog'
import type { SavedInsightLinkConfig } from '@/lib/analytics/saved-insights'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

const config: SavedInsightLinkConfig = {
  projectId: '756020',
  days: 30,
  savedInsightIds: { funnel: 'funnel01' },
}

function render(props: {
  days: number
  configOverride?: SavedInsightLinkConfig | null
}): string {
  return renderToStaticMarkup(createElement(AdminPostHogInsights, props))
}

describe('admin PostHog saved insights panel', () => {
  const page = read('../app/admin/page.tsx')
  const analytics = read('../components/admin/AdminAnalytics.tsx')
  const component = read('../components/admin/AdminPostHogInsights.tsx')
  const docs = read('../../../docs/POSTHOG.md')

  it('resolves no project config when the public project id is unset', () => {
    expect(analyticsSavedInsightConfig(30)).toBeNull()
  })

  it('renders the five catalog entries without links when PostHog is unavailable', () => {
    const html = render({ days: 30, configOverride: null })
    expect(html).toContain('PostHog saved insights')
    expect(html).toContain('PostHog not configured')
    expect(html).toContain('first-party KPI cards above still load')
    expect(html).toContain('Activation funnel')
    expect(html).toContain('Product event trends')
    expect(html).toContain('Navigation paths')
    expect(html).toContain('Weekly retention')
    expect(html).toContain('Feature stickiness')
    expect(html).toContain('link unavailable')
    expect(html).not.toContain('https://us.posthog.com')
    expect(html).not.toContain('<iframe')
  })

  it('links every view to the configured project and selected range', () => {
    const html = render({ days: 30, configOverride: config })
    expect(html).toContain('PostHog insights linked')
    expect(html).toContain('/project/756020/insights/funnel01')
    for (const type of ['FUNNELS', 'TRENDS', 'PATHS', 'RETENTION', 'STICKINESS']) {
      expect(html).toContain(`insight=${type}`)
    }
    expect(html).toContain('-30d')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noreferrer"')
    expect(html).toContain('Saved insight')
    expect(html).toContain('Prefilled draft')
    expect(html).not.toContain('<iframe')
    expect(html).not.toContain('dangerouslySetInnerHTML')
  })

  it('carries a 7-day range through every draft and saved link', () => {
    const html = render({
      days: 7,
      configOverride: { ...config, days: 7, savedInsightIds: {} },
    })
    expect(html).toContain('7-day range')
    expect(html).toContain('-7d')
    expect(html).toContain('/insights/new?insight=FUNNELS')
    expect(html).not.toContain('-30d')
  })

  it('is reachable only from the admin Analytics tab and keeps KPI loading independent', () => {
    expect(page).toContain("{ id: 'analytics', label: 'Analytics' }")
    expect(page).toContain('const tabs = canAdmin ? ADMIN_TABS : SUPPORT_TABS')
    const supportBlock = page.slice(page.indexOf('const SUPPORT_TABS'))
    expect(supportBlock.slice(0, 250)).not.toContain("id: 'analytics'")

    expect(analytics).toContain(
      "import AdminPostHogInsights from '@/components/admin/AdminPostHogInsights'",
    )
    expect(analytics).toContain('<AdminPostHogInsights days={days} />')
    expect(analytics).toContain('await apiClient.getAdminAnalyticsOverview(range)')
    const kpiIndex = analytics.indexOf('<KpiCard label="Total users"')
    const panelIndex = analytics.indexOf('<AdminPostHogInsights days={days} />')
    expect(kpiIndex).toBeGreaterThan(-1)
    expect(panelIndex).toBeGreaterThan(kpiIndex)
  })

  it('never embeds PostHog, requests person rows, or adds a public share action', () => {
    expect(component).not.toContain('<iframe')
    expect(component).not.toContain('dangerouslySetInnerHTML')
    expect(component).not.toContain('posthog-js')
    expect(component).not.toContain('user_id')
    expect(component).not.toContain('distinct_id')
    expect(component).not.toContain('console.')
    expect(component).toContain('POSTHOG_INSIGHT_EMBED_POLICY')
    expect(component).toContain('No per-user rows')
  })

  it('documents saved ids, fallback, embedding policy, and small-cohort suppression', () => {
    expect(docs).toContain('NEXT_PUBLIC_POSTHOG_INSIGHT_FUNNEL_ID')
    expect(docs).toContain('NEXT_PUBLIC_POSTHOG_INSIGHT_STICKINESS_ID')
    expect(docs).toContain('Saved insight catalog')
    expect(docs).toContain('first-party KPI cards')
    expect(docs).toContain('no iframe')
    expect(docs).toContain('fewer than five')
    expect(docs).toContain('public share')
  })
})
