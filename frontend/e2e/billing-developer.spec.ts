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
    await expect(page.getByText('₹239.25/month effective')).toBeVisible()
    await page.getByRole('link', { name: 'Sign In to Subscribe' }).click()
    await expect(page).toHaveURL(/\/login\?redirect=%2Fbilling$/)
  })

  test('current paid plan is selected and Free explains end-of-cycle cancellation', async ({ page }) => {
    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({
        json: {
          user: { id: 'user-basic', email: 'basic@example.com', name: 'Basic User' },
          session: { id: 'sess-basic', userId: 'user-basic', token: 'basic-token' },
        },
      }),
    )
    await page.route('**/subscription/plans', (route) =>
      route.fulfill({ json: plansPayload }),
    )
    await page.route('**/subscription/current', (route) =>
      route.fulfill({
        json: {
          userId: 'user-basic',
          planId: 'basic',
          planName: 'Basic',
          status: 'active',
          features: { compilations: 50, optimizations: 10, historyRetention: 30, prioritySupport: false, apiAccess: false },
          subscriptionId: 'sub_basic_1',
          currentPeriodEnd: '2099-01-01T00:00:00Z',
        },
      }),
    )

    await page.goto('/billing')
    const basicCard = page.locator('article').filter({
      has: page.getByRole('heading', { name: 'Basic', exact: true }),
    })
    await expect(basicCard.getByRole('button', { name: 'Current Plan' })).toBeDisabled()
    await expect(page.getByText(
      'Selecting Free schedules cancellation at the end of your current billing period. Your paid access continues until then.',
    )).toBeVisible()
  })

  test('failed checkout return reports the result but keeps server subscription state authoritative', async ({ page }) => {
    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({
        json: {
          user: { id: 'user-failed-checkout', email: 'failed@example.com', name: 'Test User' },
          session: { id: 'sess-failed-checkout', userId: 'user-failed-checkout', token: 'failed-checkout-token' },
        },
      }),
    )
    await page.route('**/subscription/plans', (route) =>
      route.fulfill({ json: plansPayload }),
    )
    await page.route('**/subscription/current', (route) =>
      route.fulfill({
        json: {
          userId: 'user-failed-checkout',
          planId: 'free',
          planName: 'Free Trial',
          status: 'active',
          features: { compilations: 3, optimizations: 0, historyRetention: 0, prioritySupport: false, apiAccess: false },
        },
      }),
    )

    await page.goto('/billing?checkout=return&status=failed')
    await expect(page.getByRole('status')).toHaveText(
      'This checkout was reported as unsuccessful. Your current subscription status is shown below.',
    )
    await expect(page.getByText("You're currently on the Free plan.")).toBeVisible()
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
    await expect(page.getByText('SAVE20 · 20% off')).toBeVisible()

    await expect(page.getByRole('heading', { name: 'Team seats' })).toBeVisible()
    await page.getByPlaceholder('teammate@company.com').fill('newhire@example.com')
    await page.getByRole('button', { name: 'Invite teammate' }).click()
    await expect(page.getByText('designer@example.com')).toBeVisible()
  })

  test('team invitation previews with GET and accepts only after explicit confirmation', async ({ page }) => {
    let joinPreviewCount = 0
    let joinPostCount = 0
    let subscriptionCalls = 0
    const subscription = (planId: string) => ({
      userId: 'user-member',
      planId,
      planName: planId === 'free' ? 'Free Trial' : 'Team Seat',
      status: 'active',
      features: {
        compilations: planId === 'free' ? 3 : 'unlimited',
        optimizations: planId === 'free' ? 0 : 'unlimited',
        historyRetention: planId === 'free' ? 0 : 365,
        prioritySupport: planId !== 'free',
        apiAccess: planId !== 'free',
      },
      subscriptionId: planId === 'free' ? null : 'team-seat-subscription',
      currentPeriodEnd: '2099-01-01T00:00:00Z',
    })

    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({
        json: {
          user: { id: 'user-member', email: 'member@example.com', name: 'Member' },
          session: { id: 'sess-member', userId: 'user-member', token: 'member-token' },
        },
      }),
    )
    await page.route('**/subscription/plans', (route) => route.fulfill({ json: plansPayload }))
    await page.route('**/subscription/current', (route) => {
      subscriptionCalls += 1
      return route.fulfill({ json: subscription(subscriptionCalls > 1 ? 'team_member' : 'free') })
    })
    await page.route('**/team/join/preview-token', (route) => {
      if (route.request().method() === 'GET') {
        joinPreviewCount += 1
        return route.fulfill({ json: { success: true, message: 'Team invitation is ready to accept' } })
      }
      joinPostCount += 1
      return route.fulfill({ json: { success: true, message: 'Team seat activated' } })
    })

    await page.goto('/billing?team_invite=preview-token')
    const acceptButton = page.getByRole('button', { name: 'Accept team invitation' })
    await expect(acceptButton).toBeVisible()
    expect(joinPreviewCount).toBeGreaterThan(0)
    expect(joinPostCount).toBe(0)

    await acceptButton.click()
    await expect(page.getByText('Team seat activated successfully.')).toBeVisible()
    await expect.poll(() => subscriptionCalls).toBeGreaterThan(1)
    expect(joinPostCount).toBe(1)
  })

  test('team invitation retries a transient acceptance failure', async ({ page }) => {
    let joinPostCount = 0
    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({
        json: {
          user: { id: 'user-member', email: 'member@example.com', name: 'Member' },
          session: { id: 'sess-member', userId: 'user-member', token: 'member-token' },
        },
      }),
    )
    await page.route('**/subscription/plans', (route) => route.fulfill({ json: plansPayload }))
    await page.route('**/subscription/current', (route) =>
      route.fulfill({
        json: {
          userId: 'user-member',
          planId: 'free',
          planName: 'Free Trial',
          status: 'active',
          features: plansPayload.plans.free.features,
          subscriptionId: null,
          currentPeriodEnd: null,
        },
      }),
    )
    await page.route('**/team/join/preview-token', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: { success: true, message: 'Team invitation is ready to accept' } })
      }
      joinPostCount += 1
      if (joinPostCount === 1) {
        return route.fulfill({
          status: 503,
          json: { detail: 'Invitation service is temporarily unavailable' },
        })
      }
      return route.fulfill({
        json: { success: true, message: 'Team seat activated' },
      })
    })

    await page.goto('/billing?team_invite=preview-token')
    const acceptButton = page.getByRole('button', { name: 'Accept team invitation' })
    await expect(acceptButton).toBeVisible()
    await acceptButton.click()
    await expect(
      page.locator('#main-content').getByText(/HTTP 503: Invitation service is temporarily unavailable/),
    ).toBeVisible()
    await expect(acceptButton).toBeVisible()
    await expect(acceptButton).toBeEnabled()
    await acceptButton.click()
    await expect(page.getByText('Team seat activated successfully.')).toBeVisible()
    expect(joinPostCount).toBe(2)
  })

  test('team invitation conflict removes stale acceptance guidance', async ({ page }) => {
    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({
        json: {
          user: { id: 'user-member', email: 'member@example.com', name: 'Member' },
          session: { id: 'sess-member', userId: 'user-member', token: 'member-token' },
        },
      }),
    )
    await page.route('**/subscription/plans', (route) => route.fulfill({ json: plansPayload }))
    await page.route('**/subscription/current', (route) =>
      route.fulfill({
        json: {
          userId: 'user-member',
          planId: 'free',
          planName: 'Free Trial',
          status: 'active',
          features: plansPayload.plans.free.features,
          subscriptionId: null,
          currentPeriodEnd: null,
        },
      }),
    )
    await page.route('**/team/join/conflict-token', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: { success: true, message: 'Team invitation is ready to accept' } })
      }
      return route.fulfill({
        status: 409,
        json: { detail: 'Invitation has already been accepted' },
      })
    })

    await page.goto('/billing?team_invite=conflict-token')
    const acceptButton = page.getByRole('button', { name: 'Accept team invitation' })
    await expect(acceptButton).toBeVisible()
    await acceptButton.click()
    await expect(
      page.locator('#main-content').getByText(/HTTP 409: Invitation has already been accepted/),
    ).toBeVisible()
    await expect(acceptButton).toBeHidden()
    await expect(page.getByText('Review the invitation and accept it to activate your team seat.')).toBeHidden()
  })

  test('stale invitation acceptance cannot update a switched token', async ({ page }) => {
    let session = {
      user: { id: 'user-member-a', email: 'member-a@example.com', name: 'Member A' },
      session: { id: 'sess-member-a', userId: 'user-member-a', token: 'member-a-token' },
    }
    const releaseOldAcceptance = { resolve: () => {} }
    const oldAcceptanceReleased = new Promise<void>((resolve) => { releaseOldAcceptance.resolve = resolve })

    await page.route('**/api/auth/get-session', (route) => route.fulfill({ json: session }))
    await page.route('**/subscription/plans', (route) => route.fulfill({ json: plansPayload }))
    await page.route('**/subscription/current', (route) =>
      route.fulfill({
        json: {
          userId: session.user.id,
          planId: 'free',
          planName: 'Free Trial',
          status: 'active',
          features: plansPayload.plans.free.features,
          subscriptionId: null,
          currentPeriodEnd: null,
        },
      }),
    )
    await page.route('**/team/join/*', async (route) => {
      const url = route.request().url()
      const token = url.slice(url.lastIndexOf('/') + 1)
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: { success: true, message: `Invitation ${token} is ready` } })
      }
      if (token === 'old-token') {
        await oldAcceptanceReleased
        return route.fulfill({ json: { success: true, message: 'Old account seat activated' } })
      }
      return route.fulfill({ json: { success: true, message: 'New account seat activated' } })
    })

    await page.goto('/billing?team_invite=old-token')
    const oldAcceptButton = page.getByRole('button', { name: 'Accept team invitation' })
    await expect(oldAcceptButton).toBeVisible()
    await oldAcceptButton.click()

    await page.evaluate(() => window.history.pushState({}, '', '/billing?team_invite=new-token'))
    const newAcceptButton = page.getByRole('button', { name: 'Accept team invitation' })
    await expect(newAcceptButton).toBeVisible()
    releaseOldAcceptance.resolve()

    await expect(page.getByText('Team seat activated successfully.')).toBeHidden()
    await expect(newAcceptButton).toBeVisible()
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
    await expect(page.getByRole('heading', { name: 'API keys' })).toBeVisible()
    await expect(page.getByText('Current plan: pro · 1000 requests/day')).toBeVisible()
    await expect(page.getByText('lx_sk_abcd1234')).toBeVisible()

    await page.getByPlaceholder('Production integration').fill('CI pipeline')
    await page.getByRole('button', { name: 'Create key' }).click()
    await expect(page.getByText('Copy this key now — it will never be shown again')).toBeVisible()
    await expect(page.locator('code', { hasText: 'lx_sk_full_ci_key_value' })).toBeVisible()
  })
})
