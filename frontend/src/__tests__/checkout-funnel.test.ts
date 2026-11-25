import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import {
  checkoutFailureReplayUrl,
  REPLAY_TRIAGE_ROUTES,
} from '@/lib/analytics/replay-links'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin checkout funnel', () => {
  const funnel = read('../components/admin/AdminCheckoutFunnel.tsx')
  const billing = read('../components/admin/AdminBilling.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('wires the aggregate funnel and every normalized failure bucket', () => {
    expect(billing).toContain("import AdminCheckoutFunnel from './AdminCheckoutFunnel'")
    expect(billing).toContain('<AdminCheckoutFunnel />')
    expect(funnel).toContain('getAdminCheckoutFunnel')
    expect(apiClient).toContain('/admin/billing/checkout-funnel')
    for (const bucket of ['provider_declined', 'validation', 'abandoned', 'unavailable', 'unknown']) {
      expect(funnel).toContain(bucket)
    }
    expect(funnel).toContain('started_equals_paid_plus_failed')
    expect(funnel).toContain('amount_minor')
    expect(funnel).toContain('minimum_segment_size')
  })

  it('uses the consent/masking-safe replay helper without embedding replay data', () => {
    expect(funnel).toContain('analyticsReplayTriageLinks')
    expect(funnel).toContain('checkoutFailures')
    expect(funnel).toContain('never embeds or returns replay data')
    expect(funnel).toContain('Document, share, portfolio, and editor surfaces are excluded')
    expect(funnel).not.toContain('posthog-js')
    expect(funnel).not.toContain('rrweb')
    expect(funnel).not.toContain('latex_content')
    expect(funnel).not.toContain('customer_email')
  })
})

describe('checkout failure replay filter', () => {
  it('filters only the checkout_failed event and excludes document surfaces', () => {
    const url = checkoutFailureReplayUrl({ projectId: '756020', days: 30 })
    const parsed = JSON.parse(
      decodeURIComponent(new URL(url).searchParams.get('filters') ?? '{}'),
    )
    expect(parsed.date_from).toBe('-30d')
    expect(parsed.filter_group.values[0].values).toEqual([
      { id: 'checkout_failed', type: 'events', order: 0, name: 'checkout_failed' },
    ])
    for (const route of REPLAY_TRIAGE_ROUTES) {
      expect(route.path).not.toMatch(/^\/(?:workspace|workspaces|try|r|u|share|portfolio)(?:\/|$)/)
    }
  })
})
