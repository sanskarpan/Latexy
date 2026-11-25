import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import {
  buildReplayBrowserUrl,
  describeReplayBrowserFilters,
  EMPTY_REPLAY_BROWSER_FILTERS,
  isBlockedReplaySurface,
  isReplayBrowserRoute,
  normalizeReplayBrowserFilters,
  REPLAY_BROWSER_CONSENT_COVERAGE,
  REPLAY_BROWSER_DURATION_OPTIONS,
  REPLAY_BROWSER_MASKING_POLICY,
  REPLAY_BROWSER_PLANS,
  REPLAY_BROWSER_ROUTES,
  REPLAY_BROWSER_SAVED_FILTERS,
  replayBrowserSavedFilterLinks,
} from '@/lib/analytics/replay-browser'
import { DEFAULT_POSTHOG_UI_HOST, type ReplayLinkConfig } from '@/lib/analytics/replay-links'

const config: ReplayLinkConfig = { projectId: '756020', days: 30 }
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

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

function hasFilters(url: string): boolean {
  const group = parseFilters(url).filter_group as
    | { values: Array<{ values: unknown[] }> }
    | undefined
  return Boolean(group?.values.some((value) => value.values.length > 0))
}

describe('replay browser filter contract', () => {
  it('builds a replay-home URL for the configured project and date range', () => {
    const url = buildReplayBrowserUrl(config, EMPTY_REPLAY_BROWSER_FILTERS)
    expect(url.startsWith(`${DEFAULT_POSTHOG_UI_HOST}/project/756020/replay/home?filters=`)).toBe(true)
    expect(parseFilters(url).date_from).toBe('-30d')
    expect(hasFilters(url)).toBe(false)
  })

  it('filters by sanitized route', () => {
    const url = buildReplayBrowserUrl(config, { route: '/billing' })
    expect(groupValues(url)).toEqual([
      { key: '$current_url', operator: 'icontains', type: 'event', value: '/billing' },
    ])
  })

  it('filters by plan person property', () => {
    const url = buildReplayBrowserUrl(config, { plan: 'pro' })
    expect(groupValues(url)).toEqual([
      { key: 'plan', operator: 'exact', type: 'person', value: ['pro'] },
    ])
  })

  it('filters by console error, duration, and checkout failure', () => {
    const errorUrl = buildReplayBrowserUrl(config, { error: 'console' })
    expect(groupValues(errorUrl)).toEqual([
      { key: 'level', operator: 'exact', type: 'log_entry', value: ['error'] },
    ])

    const durationUrl = buildReplayBrowserUrl(config, { minActiveSeconds: 300 })
    expect(parseFilters(durationUrl).duration).toEqual([
      { key: 'active_seconds', operator: 'gt', type: 'recording', value: 300 },
    ])

    const checkoutUrl = buildReplayBrowserUrl(config, { checkoutFailure: true })
    expect(groupValues(checkoutUrl)).toEqual([
      { id: 'checkout_failed', type: 'events', order: 0, name: 'checkout_failed' },
    ])
  })

  it('combines every dimension under one AND group', () => {
    const url = buildReplayBrowserUrl(config, {
      route: '/dashboard',
      plan: 'team',
      error: 'console',
      minActiveSeconds: 120,
      checkoutFailure: true,
    })
    expect(groupValues(url)).toEqual([
      { id: 'checkout_failed', type: 'events', order: 0, name: 'checkout_failed' },
      { key: 'level', operator: 'exact', type: 'log_entry', value: ['error'] },
      { key: '$current_url', operator: 'icontains', type: 'event', value: '/dashboard' },
      { key: 'plan', operator: 'exact', type: 'person', value: ['team'] },
    ])
    expect(parseFilters(url).duration).toEqual([
      { key: 'active_seconds', operator: 'gt', type: 'recording', value: 120 },
    ])
    expect(parseFilters(url).date_from).toBe('-30d')
  })

  it('preserves the selected days for saved and custom links', () => {
    for (const days of [7, 30, 90]) {
      const next = buildReplayBrowserUrl({ projectId: '42', days }, { route: '/pricing' })
      expect(next.startsWith(`${DEFAULT_POSTHOG_UI_HOST}/project/42/replay/home?filters=`)).toBe(true)
      expect(parseFilters(next).date_from).toBe(`-${days}d`)
    }
  })

  it('normalizes tampered input back into the closed filter contract', () => {
    expect(
      normalizeReplayBrowserFilters({
        route: '/workspace/secret/edit',
        plan: 'enterprise',
        error: 'crash' as never,
        minActiveSeconds: 0,
        checkoutFailure: true,
      }),
    ).toEqual({ ...EMPTY_REPLAY_BROWSER_FILTERS, checkoutFailure: true })

    expect(normalizeReplayBrowserFilters({ minActiveSeconds: 5 }).minActiveSeconds).toBe(30)
    expect(normalizeReplayBrowserFilters({ minActiveSeconds: 9_999 }).minActiveSeconds).toBe(3_600)
  })

  it('drops blocked routes instead of forwarding them to PostHog', () => {
    for (const route of [
      '/workspace/abc/edit',
      '/workspaces/team/recruiter',
      '/try',
      '/r/token',
      '/u/username',
      '/share/token',
      '/portfolio/username',
    ]) {
      expect(isBlockedReplaySurface(route)).toBe(true)
      const url = buildReplayBrowserUrl(config, { route })
      expect(hasFilters(url)).toBe(false)
      expect(decodeURIComponent(url)).not.toContain('abc')
      expect(decodeURIComponent(url)).not.toContain('token')
      expect(decodeURIComponent(url)).not.toContain('username')
    }
  })

  it('keeps route options on the safe allowlist', () => {
    for (const route of REPLAY_BROWSER_ROUTES) {
      expect(isReplayBrowserRoute(route.path)).toBe(true)
      expect(isBlockedReplaySurface(route.path)).toBe(false)
    }
    expect(REPLAY_BROWSER_ROUTES.map((route) => route.path)).not.toContain(
      '/workspace/:resumeId/edit',
    )
  })

  it('keeps plan options on the low-cardinality plan property', () => {
    expect(REPLAY_BROWSER_PLANS.map((plan) => plan.key)).toEqual(
      expect.arrayContaining(['free', 'basic', 'pro', 'byok', 'team']),
    )
    for (const plan of REPLAY_BROWSER_PLANS) {
      expect(plan.key).toMatch(/^[a-z]+$/)
    }
  })

  it('resolves every saved filter without leaking identifiers or blocked surfaces', () => {
    const links = replayBrowserSavedFilterLinks(config)
    expect(links.map((link) => link.id)).toEqual(
      REPLAY_BROWSER_SAVED_FILTERS.map((saved) => saved.id),
    )
    for (const link of links) {
      expect(link.href.startsWith(`${DEFAULT_POSTHOG_UI_HOST}/project/756020/replay/home?filters=`)).toBe(true)
      expect(parseFilters(link.href).date_from).toBe('-30d')
      expect(link.href).not.toMatch(/token|secret|email|phc_/i)
      expect(link.href).not.toContain('@')
      expect(decodeURIComponent(link.href)).not.toContain('/workspace')
      expect(decodeURIComponent(link.href)).not.toContain('/share/')
      expect(decodeURIComponent(link.href)).not.toContain('/portfolio/')
      expect(normalizeReplayBrowserFilters(link.filters)).toEqual(link.filters)
    }
  })

  it('covers every required saved-filter dimension', () => {
    expect(REPLAY_BROWSER_SAVED_FILTERS.some((saved) => saved.filters.route !== null)).toBe(true)
    expect(REPLAY_BROWSER_SAVED_FILTERS.some((saved) => saved.filters.plan !== null)).toBe(true)
    expect(REPLAY_BROWSER_SAVED_FILTERS.some((saved) => saved.filters.error === 'console')).toBe(true)
    expect(
      REPLAY_BROWSER_SAVED_FILTERS.some((saved) => saved.filters.minActiveSeconds !== null),
    ).toBe(true)
    expect(
      REPLAY_BROWSER_SAVED_FILTERS.some((saved) => saved.filters.checkoutFailure),
    ).toBe(true)
    expect(REPLAY_BROWSER_DURATION_OPTIONS.map((option) => option.value)).toEqual(
      expect.arrayContaining([60, 120, 300, 600]),
    )
  })

  it('describes active filters for the UI and screen readers', () => {
    expect(describeReplayBrowserFilters(EMPTY_REPLAY_BROWSER_FILTERS)).toBe('All replays')
    expect(
      describeReplayBrowserFilters({
        route: '/billing',
        plan: 'pro',
        error: 'console',
        minActiveSeconds: 120,
        checkoutFailure: true,
      }),
    ).toBe('Billing · Pro plan · console errors · over 2 active minutes · checkout failures')
  })

  it('states consent coverage and masking policy with no disable switch', () => {
    expect(REPLAY_BROWSER_CONSENT_COVERAGE.model).toBe('Opt-in only')
    expect(REPLAY_BROWSER_CONSENT_COVERAGE.captureBeforeConsent).toBe('Disabled')
    expect(REPLAY_BROWSER_CONSENT_COVERAGE.gatedRoutes).toContain('All')
    expect(REPLAY_BROWSER_CONSENT_COVERAGE.excludedSurfaces.join(' ')).toMatch(/share/i)
    expect(REPLAY_BROWSER_CONSENT_COVERAGE.excludedSurfaces.join(' ')).toMatch(/portfolio/i)
    expect(REPLAY_BROWSER_MASKING_POLICY.textNodes).toBe('All masked')
    expect(REPLAY_BROWSER_MASKING_POLICY.inputs).toBe('All masked')
    expect(REPLAY_BROWSER_MASKING_POLICY.elementAttributes).toBe('All masked')
    expect(REPLAY_BROWSER_MASKING_POLICY.disableMasking).toBe('Not available')
  })
})

describe('admin replay browser view contract', () => {
  const component = read('../components/admin/AdminReplayBrowser.tsx')
  const page = read('../app/admin/page.tsx')
  const analytics = read('../components/admin/AdminAnalytics.tsx')

  it('renders the replay browser only through the admin tab list', () => {
    expect(page).toContain("import AdminReplayBrowser from '@/components/admin/AdminReplayBrowser'")
    expect(page).toContain("{ id: 'replays', label: 'Replays' }")
    expect(page).toContain("tab === 'replays' && <AdminReplayBrowser />")
    expect(page).toContain('const tabs = canAdmin ? ADMIN_TABS : SUPPORT_TABS')
    expect(analytics).toContain('href="/admin?tab=replays"')
    expect(analytics).toContain('Replay library')
  })

  it('renders saved filters and every filter control', () => {
    expect(component).toContain('Session replay library')
    expect(component).toContain('Saved filters')
    expect(component).toContain('replayBrowserSavedFilterLinks')
    expect(component).toContain('aria-label="Replay route filter"')
    expect(component).toContain('aria-label="Replay plan filter"')
    expect(component).toContain('aria-label="Replay error filter"')
    expect(component).toContain('aria-label="Replay duration filter"')
    expect(component).toContain('Checkout failure')
    expect(component).toContain('Open filtered replay list')
  })

  it('states consent coverage and masking without embedding replay data', () => {
    expect(component).toContain('Consent coverage and masking policy')
    expect(component).toContain('REPLAY_BROWSER_CONSENT_COVERAGE')
    expect(component).toContain('REPLAY_BROWSER_MASKING_POLICY')
    expect(component).toContain('no disable-masking control')
    expect(component).not.toContain('<iframe')
    expect(component).not.toContain('dangerouslySetInnerHTML')
    expect(component).not.toContain('posthog-js')
    expect(component).not.toContain('console.log')
    expect(component).not.toContain('console.error')
    expect(component).not.toContain('role="switch"')
  })

  it('opens every PostHog link in a new tab without a token in the URL', () => {
    expect(component).toContain('target="_blank"')
    expect(component).toContain('rel="noreferrer"')
    expect(component).toContain('analyticsReplayTriageLinks(days)')
    expect(component).toContain('analyticsReplayLinkConfig(days)')
    expect(component).not.toMatch(/POSTHOG_KEY|phc_|api[_-]?key/i)
  })
})
