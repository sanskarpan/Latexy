import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin control room surfaces', () => {
  const page = read('../app/admin/page.tsx')
  const billing = read('../components/admin/AdminBilling.tsx')
  const analytics = read('../components/admin/AdminAnalytics.tsx')
  const growth = read('../components/admin/AdminGrowth.tsx')
  const userDetail = read('../components/admin/AdminUserDetail.tsx')
  const audit = read('../components/admin/AdminAudit.tsx')
  const operations = read('../components/admin/AdminOperations.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('wires revenue, growth, customers, audit, and support-only navigation', () => {
    expect(page).toContain("import AdminBilling from '@/components/admin/AdminBilling'")
    expect(page).toContain("import AdminGrowth from '@/components/admin/AdminGrowth'")
    expect(page).toContain("import AdminAudit from '@/components/admin/AdminAudit'")
    expect(page).toContain("import AdminUserDetail from '@/components/admin/AdminUserDetail'")
    expect(page).toContain("const SUPPORT_TABS")
    expect(page).toContain("tab === 'billing' && <AdminBilling />")
    expect(page).toContain("tab === 'growth' && <AdminGrowth />")
    expect(page).toContain("tab === 'customers' && <UsersTab canAdmin={canAdmin} />")
    expect(page).toContain("tab === 'audit' && <AdminAudit />")
    expect(analytics).toContain("import AdminOperations from '@/components/admin/AdminOperations'")
    expect(analytics).toContain('<AdminOperations />')
    expect(analytics).toContain('kpi_trends')
    expect(analytics).toContain('vs prior period')
    expect(analytics).toContain('Sparkline')
    expect(analytics).toContain('baseline_zero')
    expect(page).toContain("new URLSearchParams(window.location.search).get('tab')")
    expect(page).toContain('id="admin-job-queue"')
  })

  it('wires the attention queue and operations health with independent failure states', () => {
    expect(operations).toContain('Needs attention')
    expect(operations).toContain('System health')
    expect(operations).toContain('getAdminAttention')
    expect(operations).toContain('getAdminOperationsHealth')
    expect(operations).toContain('Showing the last successful data')
    expect(operations).not.toContain('latex_content')
    expect(operations).not.toContain('customer_email')
    expect(apiClient).toContain("'/admin/operations/attention'")
    expect(apiClient).toContain("'/admin/operations/health'")
    expect(billing).toContain('id="admin-billing-webhooks"')
  })

  it('shows activation, retention, cost, and filtered series without document content', () => {
    expect(growth).toContain('Activation funnel')
    expect(growth).toContain('Weekly retention')
    expect(growth).toContain('Estimated AI cost')
    expect(growth).toContain('Dimension explorer')
    expect(growth).toContain('minimum_cohort_size')
    expect(growth).not.toContain('latex_content')
  })

  it('keeps refund execution behind approval and webhook review explicit', () => {
    expect(billing).toContain('Reconcile from Dodo')
    expect(billing).toContain('Acknowledge')
    expect(billing).toContain('createAdminRefundRequest')
    expect(billing).toContain('decideAdminRefund')
    expect(billing).toContain('executeAdminRefund')
    expect(billing).not.toContain('DODO_API_KEY')
    expect(billing).not.toContain('dodo_api_key')
  })

  it('masks PII by default and gates support mutations', () => {
    expect(userDetail).toContain('canAdmin')
    expect(userDetail).toContain('Reveal email and name')
    expect(userDetail).toContain('Support access is read-only')
    expect(userDetail).toContain('revokeAdminUserSessions')
    expect(userDetail).toContain('resetAdminUserQuota')
    expect(audit.toLowerCase()).toContain('append-only')
    expect(audit).toContain('UPDATE and DELETE')
  })
})

describe('PostHog privacy hardening', () => {
  const provider = read('../components/analytics/AnalyticsProvider.tsx')
  const wrapper = read('../lib/analytics/posthog.ts')
  const share = read('../app/r/[token]/page.tsx')
  const guard = read('../../../scripts/ci/no-session-recording.sh')

  it('reacts to cross-tab consent withdrawal and resets between accounts', () => {
    expect(provider).toContain("window.addEventListener('storage', onStorage)")
    expect(provider).toContain('ANALYTICS_CONSENT_KEY')
    expect(provider).toContain('identifiedUserId.current !== user.id')
    expect(provider.indexOf('resetAnalyticsUser()')).toBeLessThan(provider.indexOf('identifyAnalyticsUser({'))
  })

  it('masks replay attributes in the recording config and blocks every share branch', () => {
    expect(wrapper).toContain('maskAllElementAttributes: true')
    expect((share.match(/data-ph-no-capture/g) ?? []).length).toBeGreaterThanOrEqual(4)
    expect(guard).toContain('maskAllElementAttributes: true')
    expect(guard).toContain('share_markers')
  })
})
