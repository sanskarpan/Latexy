import { test, expect, type Page } from '@playwright/test'

const MOCK_SESSION = {
  session: { id: 'sess-admin', userId: 'user-admin', token: 'admin-token' },
  user: { id: 'user-admin', email: 'admin@example.com', name: 'Admin User' },
}

const USER_360 = {
  user: {
    id: 'user-1',
    email: 'u***@example.com',
    name: 'Te** Us**',
    pii_masked: true,
    role: 'user',
    subscription_plan: 'free',
    subscription_status: 'active',
    email_verified: true,
    two_factor_enabled: false,
    trial_used: false,
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    public_username: null,
    portfolio_enabled: false,
    default_tenant_id: null,
  },
  activation: {
    has_resume: false,
    has_compile: false,
    has_optimization: false,
    has_export: false,
    has_paid: false,
    last_activity_at: null,
  },
  usage: { events_30d: 0, actions: [], recent_events: [] },
  production: {
    resumes: 0,
    recent_resumes: [],
    compilations: 0,
    successful_compilations: 0,
    failed_compilations: 0,
    last_compilation_at: null,
    optimizations: 0,
    last_optimization_at: null,
  },
  integrations: { github: false, dropbox: false, zotero: false, mendeley: false },
  billing: {
    subscriptions: [],
    // Deliberately null currency: older provider rows can carry this shape.
    payments: [
      {
        id: 'pay-1',
        provider_payment_id: 'pay_123456789',
        amount: 1000,
        currency: null,
        status: 'paid',
        payment_method: null,
        created_at: '2026-11-01T00:00:00Z',
      },
    ],
    refunds: [],
    refund_requests: [],
    timeline: {
      items: [
        {
          id: 'payment:pay-1',
          kind: 'payment',
          occurred_at: '2026-11-01T00:00:00Z',
          summary: 'Payment · paid · 10.00 INR',
          event_type: 'payment',
          source: 'billing',
          status: 'paid',
          previous_status: null,
          plan_id: null,
          previous_plan_id: null,
          current_period_start: null,
          current_period_end: null,
          reason_code: null,
          amount_minor: 1000,
          currency: 'INR',
          provider: 'dodo',
          reference: 'pay_123456789',
          admin_only: false,
        },
        {
          id: 'subscription_history:hist-1',
          kind: 'subscription_history',
          occurred_at: '2026-10-31T00:00:00Z',
          summary: 'plan changed · basic → pro',
          event_type: 'plan_changed',
          source: 'billing',
          status: 'active',
          previous_status: 'active',
          plan_id: 'pro',
          previous_plan_id: 'basic',
          current_period_start: null,
          current_period_end: null,
          reason_code: 'plan_change',
          amount_minor: null,
          currency: null,
          provider: null,
          reference: null,
          admin_only: false,
        },
      ],
      total: 2,
      limit: 20,
      offset: 0,
      has_more: false,
      next_offset: null,
      order: 'desc',
      viewer_role: 'admin',
      restricted_kinds: [],
      counts: { payment: 1, subscription_history: 1 },
      sources: {
        subscription_history: 1,
        subscriptions: 0,
        payments: 1,
        refunds: 0,
        webhooks: 0,
        plan_changes: 0,
        entitlement_changes: 0,
      },
      totals: {
        payments: {
          count: 1,
          total_minor: 1000,
          paid_minor: 1000,
          by_status: [{ status: 'paid', count: 1, amount_minor: 1000 }],
          by_currency: [{ currency: 'INR', count: 1, amount_minor: 1000 }],
        },
        refunds: {
          count: 0,
          total_minor: 0,
          succeeded_minor: 0,
          by_status: [],
          by_currency: [],
        },
        gross_minor: 1000,
        refunded_minor: 0,
        net_minor: 1000,
        settled_net_minor: 1000,
      },
    },
  },
  security: {
    sessions: [],
    session_count: 0,
    passkey_count: 0,
    passkeys: [],
    byok_keys: [],
    developer_keys: [],
  },
  entitlements: {
    effective: {},
    overrides: {},
    available_features: [],
    available: true,
  },
  quota: {
    period: '2026-11',
    resets_at: '2026-12-01T00:00:00Z',
    policy_available: true,
    authority_available: true,
    dimensions: {},
  },
  trial: {
    trial_used: false,
    eligible: true,
    extended_until: null,
    updated_at: null,
    updated_by: null,
    source: 'account',
  },
  recent_admin_actions: [],
}

async function mockAdmin(page: Page) {
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SESSION) })
  )
  await page.route('**/me', (route) =>
    route.fulfill({ json: { id: 'user-admin', role: 'admin', preferences: {} } })
  )
  await page.route((url) => url.pathname === '/config/entitlements', (route) =>
    route.fulfill({ json: { features: {} } })
  )
  await page.route('**/admin/entitlements', (route) =>
    route.fulfill({ json: { registry: [], kill_switches: {}, matrix: {}, plan_families: [] } })
  )
  await page.route((url) => url.pathname === '/config/feature-flags', (route) =>
    route.fulfill({ json: {} })
  )
  await page.route((url) => url.pathname === '/admin/users', (route) =>
    route.fulfill({
      json: {
        users: [
          {
            id: 'user-1',
            email: 'user@example.com',
            name: 'Test User',
            role: 'user',
            subscription_plan: 'free',
            email_verified: true,
            created_at: '2026-11-01T00:00:00Z',
          },
        ],
        total: 1,
      },
    })
  )
  await page.route((url) => url.pathname === '/admin/users/user-1/360', (route) =>
    route.fulfill({ json: USER_360 })
  )
}

test('opens User 360, renders it in view, and survives a null payment currency', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await mockAdmin(page)

  await page.goto('/admin', { waitUntil: 'domcontentloaded' })
  await page.getByRole('tab', { name: 'Customers', exact: true }).click()
  await expect(page.getByText('user@example.com')).toBeVisible()

  await page.getByRole('button', { name: 'View 360' }).click()
  await expect(page.getByText('Activation and usage')).toBeVisible()
  await expect(page.locator('#admin-user-360')).toBeInViewport()
  await expect(page.getByText('pay_123456789').first()).toBeVisible()
  await expect(page.getByText('Subscription and payment timeline')).toBeVisible()
  await expect(page.getByText('Payment · paid · 10.00 INR').first()).toBeVisible()
  await expect(page.getByText('plan changed · basic → pro')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Older' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Reveal email in timeline' })).toBeVisible()

  expect(pageErrors).toEqual([])
})
