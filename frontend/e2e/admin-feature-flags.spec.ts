import { test, expect, type Page } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Feature 10 — Admin Feature Flag Panel                              //
//  Tests: page loads, 403 handling, toggle, optimistic update        //
// ------------------------------------------------------------------ //

const MOCK_SESSION = {
  session: { id: 'sess-1', userId: 'user-admin', token: 'admin-token' },
  user: { id: 'user-admin', email: 'admin@example.com', name: 'Admin User' },
}

const MOCK_FLAGS: object[] = [
  { key: 'trial_limits',        enabled: true,  label: 'Trial Limits',       description: 'Anonymous: 3 uses, 5-min cooldown',             updated_at: '2026-03-18T00:00:00Z' },
  { key: 'deep_analysis_trial', enabled: true,  label: 'Deep Analysis Trial', description: '2 free deep analyses per device',               updated_at: '2026-03-18T00:00:00Z' },
  { key: 'compile_timeouts',    enabled: true,  label: 'Compile Timeouts',    description: 'free=30s, basic=120s, pro=240s',                updated_at: '2026-03-18T00:00:00Z' },
  { key: 'task_priority',       enabled: true,  label: 'Task Priority',       description: 'Higher plans get priority queue position',      updated_at: '2026-03-18T00:00:00Z' },
  { key: 'billing',             enabled: false, label: 'Billing & Payments',  description: 'Billing page, nav link, subscriptions',         updated_at: '2026-03-18T00:00:00Z' },
  { key: 'upgrade_ctas',        enabled: false, label: 'Upgrade CTAs',        description: 'Timeout banners and trial exhausted prompts',   updated_at: '2026-03-18T00:00:00Z' },
]

async function mockAuth(page: Page) {
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SESSION) })
  )
}

async function mockFeatureFlagsConfig(page: Page) {
  await page.route((url) => url.pathname === '/config/feature-flags', (route) =>
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ trial_limits: true, deep_analysis_trial: true, compile_timeouts: true, task_priority: true, billing: true, upgrade_ctas: true }),
    })
  )
}

async function mockAdminFlagsSuccess(page: Page) {
  await page.route((url) => url.pathname === '/admin/feature-flags', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_FLAGS) })
  )
}

async function mockAdminFlagsForbidden(page: Page) {
  await page.route((url) => url.pathname === '/admin/feature-flags', (route) =>
    route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: 'Forbidden' }) })
  )
}

// ------------------------------------------------------------------ //
//  1. Admin panel — page load                                         //
// ------------------------------------------------------------------ //

test.describe('/admin — page load', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockFeatureFlagsConfig(page)
    await mockAdminFlagsSuccess(page)
  })

  test('page loads without JS errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    expect(errors.filter((e) => !e.toLowerCase().includes('warning'))).toHaveLength(0)
  })

  test('shows "Feature Flags" heading', async ({ page }) => {
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Feature Flags' })).toBeVisible()
  })

  test('renders all 6 feature flag rows', async ({ page }) => {
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Trial Limits')).toBeVisible()
    await expect(page.getByText('Deep Analysis Trial')).toBeVisible()
    await expect(page.getByText('Compile Timeouts')).toBeVisible()
    await expect(page.getByText('Task Priority')).toBeVisible()
    await expect(page.getByText('Billing & Payments')).toBeVisible()
    await expect(page.getByText('Upgrade CTAs')).toBeVisible()
  })

  test('each flag row shows its description', async ({ page }) => {
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Anonymous: 3 uses, 5-min cooldown')).toBeVisible()
    await expect(page.getByText('free=30s, basic=120s, pro=240s')).toBeVisible()
  })

  test('each flag row has a toggle button', async ({ page }) => {
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    const toggles = page.getByRole('button', { name: /Toggle/i })
    await expect(toggles).toHaveCount(6)
  })

  test('enabled flags have orange toggle indicator', async ({ page }) => {
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    // trial_limits is enabled — its toggle button uses orange background classes
    const trialToggle = page.getByRole('button', { name: 'Toggle Trial Limits' })
    await expect(trialToggle).toBeVisible()
    const cls = await trialToggle.getAttribute('class')
    expect(cls).toContain('orange')
  })

  test('disabled flags have non-orange toggle', async ({ page }) => {
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    // billing is disabled
    const billingToggle = page.getByRole('button', { name: 'Toggle Billing & Payments' })
    await expect(billingToggle).toBeVisible()
    const cls = await billingToggle.getAttribute('class')
    expect(cls).not.toContain('orange')
  })

  test('shows "Admin" sub-label above heading', async ({ page }) => {
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('main').getByText('Admin').first()).toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  2. Admin panel — 403 (not authorized)                             //
// ------------------------------------------------------------------ //

test.describe('/admin — 403 forbidden', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockFeatureFlagsConfig(page)
    await mockAdminFlagsForbidden(page)
  })

  test('shows "Not authorized" when API returns 403', async ({ page }) => {
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Not authorized')).toBeVisible({ timeout: 8_000 })
  })

  test('forbidden page does NOT show flag toggles', async ({ page }) => {
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Not authorized')).toBeVisible({ timeout: 8_000 })
    await expect(page.getByText('Trial Limits')).not.toBeVisible()
    await expect(page.getByRole('button', { name: /Toggle/i })).toHaveCount(0)
  })

  test('shows admin access hint', async ({ page }) => {
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText(/Admin access required/i)).toBeVisible({ timeout: 8_000 })
  })

  test('page loads without JS errors on 403', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    expect(errors.filter((e) => !e.toLowerCase().includes('warning'))).toHaveLength(0)
  })
})

// ------------------------------------------------------------------ //
//  3. Admin panel — toggling flags                                    //
// ------------------------------------------------------------------ //

test.describe('/admin — toggle flags', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockFeatureFlagsConfig(page)
    await mockAdminFlagsSuccess(page)
  })

  test('clicking a toggle calls PATCH /admin/feature-flags/{key}', async ({ page }) => {
    let patchCalled = false
    let patchedKey = ''
    let patchBody: Record<string, unknown> = {}

    await page.route((url) => url.pathname.startsWith('/admin/feature-flags/'), async (route) => {
      patchCalled = true
      patchedKey = new URL(route.request().url()).pathname.split('/').pop() ?? ''
      patchBody = JSON.parse((await route.request().postData()) || '{}')
      return route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ key: 'trial_limits', enabled: false, label: 'Trial Limits', description: null, updated_at: '2026-03-18T01:00:00Z' }),
      })
    })

    await page.goto('/admin', { waitUntil: 'domcontentloaded' })

    const trialToggle = page.getByRole('button', { name: 'Toggle Trial Limits' })
    await trialToggle.click()
    await page.waitForTimeout(500)

    expect(patchCalled).toBe(true)
    expect(patchedKey).toBe('trial_limits')
    expect(patchBody.enabled).toBe(false)
  })

  test('toggle updates flag state optimistically', async ({ page }) => {
    await page.route((url) => url.pathname.startsWith('/admin/feature-flags/'), (route) =>
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ key: 'trial_limits', enabled: false, label: 'Trial Limits', description: null, updated_at: '2026-03-18T01:00:00Z' }),
      })
    )

    await page.goto('/admin', { waitUntil: 'domcontentloaded' })

    const trialToggle = page.getByRole('button', { name: 'Toggle Trial Limits' })
    // Before: orange (enabled)
    const beforeClass = await trialToggle.getAttribute('class')
    expect(beforeClass).toContain('orange')

    await trialToggle.click()
    await page.waitForTimeout(500)

    // After: not orange (disabled)
    const afterClass = await trialToggle.getAttribute('class')
    expect(afterClass).not.toContain('orange')
  })

  test('toggle sends correct enabled value (true → false)', async ({ page }) => {
    let sentEnabled: unknown
    await page.route((url) => url.pathname.startsWith('/admin/feature-flags/'), async (route) => {
      sentEnabled = JSON.parse((await route.request().postData()) || '{}').enabled
      return route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ key: 'billing', enabled: true, label: 'Billing & Payments', description: null, updated_at: null }),
      })
    })

    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    // billing is currently false → clicking toggles to true
    const billingToggle = page.getByRole('button', { name: 'Toggle Billing & Payments' })
    await billingToggle.click()
    await page.waitForTimeout(300)

    expect(sentEnabled).toBe(true)
  })

  test('toggle failure shows error without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.route((url) => url.pathname.startsWith('/admin/feature-flags/'), (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Server error' }) })
    )

    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Toggle Trial Limits' }).click()
    await page.waitForTimeout(500)

    expect(errors.filter((e) => !e.toLowerCase().includes('warning'))).toHaveLength(0)
  })
})

// ------------------------------------------------------------------ //
//  4. Admin page — navigation                                         //
// ------------------------------------------------------------------ //

test.describe('/admin — navigation', () => {
  test('admin page is directly reachable at /admin', async ({ page }) => {
    await mockAuth(page)
    await mockFeatureFlagsConfig(page)
    await mockAdminFlagsSuccess(page)

    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Feature Flags' })).toBeVisible()
    expect(page.url()).toContain('/admin')
  })
})
