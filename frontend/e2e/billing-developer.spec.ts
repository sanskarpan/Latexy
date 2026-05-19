import { expect, test } from '@playwright/test'

const plansPayload = {
  plans: {
    free: {
      name: 'Free Trial',
      price: 0,
      currency: 'INR',
      interval: 'month',
      features: { compilations: 3, optimizations: 0, historyRetention: 0, prioritySupport: false, apiAccess: false },
    },
    basic: {
      name: 'Basic',
      price: 29900,
      currency: 'INR',
      interval: 'month',
      features: { compilations: 50, optimizations: 10, historyRetention: 30, prioritySupport: false, apiAccess: false },
    },
    basic_annual: {
      name: 'Basic Annual',
      price: 287100,
      currency: 'INR',
      interval: 'year',
      discount_percent: 20,
      monthly_equivalent_price: 23925,
      features: { compilations: 50, optimizations: 10, historyRetention: 30, prioritySupport: false, apiAccess: false },
    },
    pro: {
      name: 'Pro',
      price: 59900,
      currency: 'INR',
      interval: 'month',
      features: { compilations: 'unlimited', optimizations: 'unlimited', historyRetention: 365, prioritySupport: true, apiAccess: true },
    },
    pro_annual: {
      name: 'Pro Annual',
      price: 575000,
      currency: 'INR',
      interval: 'year',
      discount_percent: 20,
      monthly_equivalent_price: 47917,
      features: { compilations: 'unlimited', optimizations: 'unlimited', historyRetention: 365, prioritySupport: true, apiAccess: true },
    },
    byok: {
      name: 'BYOK (Bring Your Own Key)',
      price: 19900,
      currency: 'INR',
      interval: 'month',
      features: { compilations: 'unlimited', optimizations: 'unlimited', historyRetention: 365, prioritySupport: true, apiAccess: true, customModels: true },
    },
    byok_annual: {
      name: 'BYOK Annual',
      price: 191000,
      currency: 'INR',
      interval: 'year',
      discount_percent: 20,
      monthly_equivalent_price: 15917,
      features: { compilations: 'unlimited', optimizations: 'unlimited', historyRetention: 365, prioritySupport: true, apiAccess: true, customModels: true },
    },
    student: {
      name: 'Student',
      price: 29900,
      currency: 'INR',
      interval: 'month',
      requires_student_verification: true,
      features: { compilations: 'unlimited', optimizations: 'unlimited', historyRetention: 365, prioritySupport: true, apiAccess: true },
    },
    team: {
      name: 'Team',
      price: 249900,
      currency: 'INR',
      interval: 'month',
      max_seats: 5,
      features: { compilations: 'unlimited', optimizations: 'unlimited', historyRetention: 365, prioritySupport: true, apiAccess: true, teamSeats: 5 },
    },
  },
  billing: {
    feature_enabled: true,
    mode: 'enabled',
    available: true,
    reason: null,
    message: 'Billing is available.',
  },
}

test.describe('Billing page', () => {
  test('guest can view pricing and annual toggle updates plan set', async ({ page }) => {
    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({ json: { user: null, session: null } }),
    )
    await page.route('**/subscription/plans', (route) =>
      route.fulfill({ json: plansPayload }),
    )

    await page.goto('/billing')
    await expect(page.getByRole('heading', { name: 'Pricing & Billing' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Basic' })).toBeVisible()
    await page.getByRole('button', { name: 'Annual' }).click()
    await expect(page.getByRole('heading', { name: 'Basic Annual' })).toBeVisible()
    await expect(page.getByText('₹239/month effective')).toBeVisible()
  })

  test('coupon input validates and signed-in team user can manage seats', async ({ page }) => {
    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({
        json: {
          user: { id: 'user-team', email: 'owner@example.com', name: 'Owner' },
          session: { id: 'sess-team', userId: 'user-team', token: 'team-token' },
        },
      }),
    )
    await page.route('**/subscription/plans', (route) =>
      route.fulfill({ json: plansPayload }),
    )
    await page.route('**/subscription/current', (route) =>
      route.fulfill({
        json: {
          userId: 'user-team',
          planId: 'team',
          planName: 'Team',
          status: 'active',
          features: { compilations: 'unlimited', optimizations: 'unlimited', historyRetention: 365, prioritySupport: true, apiAccess: true, teamSeats: 5 },
          subscriptionId: 'sub_team_1',
          currentPeriodEnd: '2099-01-01T00:00:00Z',
        },
      }),
    )
    await page.route('**/billing/validate-coupon', (route) =>
      route.fulfill({ json: { valid: true, message: 'Coupon applied', discountPercent: 20, code: 'SAVE20' } }),
    )
    await page.route('**/team/seats', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          json: [
            {
              id: 'seat-1',
              member_email: 'designer@example.com',
              member_user_id: null,
              status: 'invited',
              invited_at: '2026-05-19T00:00:00Z',
              joined_at: null,
            },
          ],
        })
      }
    })
    await page.route('**/team/invite', (route) =>
      route.fulfill({
        status: 201,
        json: {
          id: 'seat-2',
          member_email: 'newhire@example.com',
          member_user_id: null,
          status: 'invited',
          invited_at: '2026-05-19T00:00:00Z',
          joined_at: null,
          invite_preview_url: 'http://localhost:5181/billing?team_invite=preview-token',
          message: 'Team invitation created',
        },
      }),
    )
    await page.route('**/team/seats/*', (route) =>
      route.fulfill({ status: 204, body: '' }),
    )

    await page.goto('/billing')
    await page.getByPlaceholder('SAVE20').fill('SAVE20')
    await page.getByRole('button', { name: 'Apply' }).click()
    await expect(page.getByText('Coupon applied (20% off)')).toBeVisible()

    await expect(page.getByRole('heading', { name: 'Team seats' })).toBeVisible()
    await page.getByPlaceholder('teammate@company.com').fill('newhire@example.com')
    await page.getByRole('button', { name: 'Invite teammate' }).click()
    await expect(page.getByText('designer@example.com')).toBeVisible()
  })
})

test.describe('Developer portal', () => {
  test('authenticated user can view, create, and revoke developer keys', async ({ page }) => {
    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({
        json: {
          user: { id: 'user-dev', email: 'dev@example.com', name: 'Dev' },
          session: { id: 'sess-dev', userId: 'user-dev', token: 'dev-token' },
        },
      }),
    )
    await page.route('**/developer/keys', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          json: [
            {
              id: 'key-1',
              name: 'Production',
              key_prefix: 'lx_sk_abcd1234',
              last_used_at: '2026-05-19T00:00:00Z',
              request_count: 42,
              is_active: true,
              scopes: ['compile', 'optimize', 'ats'],
              created_at: '2026-05-18T00:00:00Z',
            },
          ],
        })
      } else if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 201,
          json: {
            id: 'key-2',
            name: 'CI pipeline',
            key_prefix: 'lx_sk_ci123456',
            last_used_at: null,
            request_count: 0,
            is_active: true,
            scopes: ['compile', 'optimize', 'ats', 'export'],
            created_at: '2026-05-19T00:00:00Z',
            full_key: 'lx_sk_full_ci_key_value',
          },
        })
      }
    })
    await page.route('**/developer/usage', (route) =>
      route.fulfill({
        json: {
          plan_id: 'pro',
          daily_limit: 1000,
          history: [
            { date: '2026-05-13', count: 4 },
            { date: '2026-05-14', count: 8 },
            { date: '2026-05-15', count: 6 },
            { date: '2026-05-16', count: 10 },
            { date: '2026-05-17', count: 7 },
            { date: '2026-05-18', count: 9 },
            { date: '2026-05-19', count: 12 },
          ],
        },
      }),
    )
    await page.route('**/developer/keys/*', async (route) => {
      if (route.request().method() === 'DELETE') {
        await route.fulfill({ status: 204, body: '' })
      } else if (route.request().method() === 'PATCH') {
        await route.fulfill({
          json: {
            id: 'key-1',
            name: 'Renamed key',
            key_prefix: 'lx_sk_abcd1234',
            last_used_at: '2026-05-19T00:00:00Z',
            request_count: 42,
            is_active: true,
            scopes: ['compile', 'optimize', 'ats'],
            created_at: '2026-05-18T00:00:00Z',
          },
        })
      }
    })

    await page.goto('/developer')
    await expect(page.getByRole('heading', { name: 'Developer API' })).toBeVisible()
    await expect(page.getByText('Current plan: pro • 1000 requests/day')).toBeVisible()
    await expect(page.getByText('lx_sk_abcd1234')).toBeVisible()

    await page.getByPlaceholder('Production integration').fill('CI pipeline')
    await page.getByRole('button', { name: 'Create key' }).click()
    await expect(page.getByText('Copy this key now. It will never be shown again.')).toBeVisible()
    await expect(page.locator('code', { hasText: 'lx_sk_full_ci_key_value' })).toBeVisible()
  })
})
