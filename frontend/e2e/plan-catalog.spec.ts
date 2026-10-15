import { expect, test, type Page } from '@playwright/test'

const backendOrigin = new URL(process.env.PLAYWRIGHT_API_URL ?? process.env.PLAYWRIGHT_BACKEND_URL ?? `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_PORT ?? '5181') + 2000}`).origin

const makeCatalog = () => ({
  plans: {
    free: {
      id: 'free', name: 'Free', description: 'No payment required.', price: 0, currency: 'INR', interval: 'month',
      billing_period: 'monthly', plan_family: 'free', version: 1, visible: true, purchase_enabled: true, purchasable: true, display_order: 0,
      quotas: { compilations: { limit: 10 as number | null, window: 'day', version: 1, source: 'configured_default' } },
      features: { compilations: '10 / day', optimizations: '3 / month', historyRetention: 0, prioritySupport: false, apiAccess: true, apiDailyLimit: 10 },
    },
    pro: {
      id: 'pro', name: 'Pro', description: 'The full toolchain.', price: 59900, currency: 'INR', interval: 'month',
      billing_period: 'monthly', plan_family: 'pro', version: 1, visible: true, purchase_enabled: true, purchasable: true, display_order: 1,
      features: { compilations: 'unlimited', optimizations: 'unlimited', historyRetention: 365, prioritySupport: true, apiAccess: true, apiDailyLimit: 1000 },
    },
    pro_annual: {
      id: 'pro_annual', name: 'Pro Annual', description: 'Annual Pro.', price: 575000, currency: 'INR', interval: 'year',
      billing_period: 'annual', plan_family: 'pro', version: 1, visible: true, purchase_enabled: false, purchasable: false, display_order: 2, unavailable_reason: 'Sales paused',
      features: { compilations: 'unlimited', optimizations: 'unlimited', historyRetention: 365, prioritySupport: true, apiAccess: true, apiDailyLimit: 1000 },
    },
  },
  editable_fields: ['name', 'description', 'display_order', 'visible', 'purchase_enabled'],
  pricing_policy: 'Provider prices are immutable. Existing subscriptions are unchanged.',
  quota_policy: 'Quota edits apply to all subscribers, including existing subscribers. Reset windows remain fixed.',
})

async function setup(page: Page) {
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url())
    if (url.origin === backendOrigin) return route.fulfill({ status: 403, json: { detail: `Unmocked fixture endpoint: ${url.pathname}` } })
    return route.continue()
  })
  await page.route('**/api/auth/get-session', (route) => route.fulfill({ json: {
    session: { id: 'catalog-session', userId: 'catalog-admin', token: 'catalog-token' },
    user: { id: 'catalog-admin', email: 'admin@example.com', name: 'Catalog Admin' },
  } }))
  await page.route('**/me', (route) => route.fulfill({ json: { id: 'catalog-admin', role: 'admin', preferences: {} } }))
  await page.route('**/config/feature-flags', (route) => route.fulfill({ json: { billing: true, upgrade_ctas: true } }))
  await page.route((url) => url.pathname === '/config/entitlements', (route) => {
    expect(new URL(route.request().url()).searchParams.get('include_quotas')).toBe('false')
    return route.fulfill({ json: { features: { i01: true }, plan_family: 'free' } })
  })
  await page.route('**/subscription/current', (route) => route.fulfill({ json: {
    userId: 'catalog-admin', planId: 'free', planName: 'Free', status: 'active', features: {},
  } }))
  await page.route('**/admin/feature-flags', (route) => route.fulfill({ json: [] }))
}

test('billing loads current catalog, retries errors and respects annual sale pause', async ({ page }) => {
  await setup(page)
  let outageRequests = 0
  let recoveredRequests = 0
  await page.addInitScript(() => {
    // Observe the real UI action before React dispatches its fetch. Automatic
    // session/entitlement refetches must not end the outage before this click.
    document.addEventListener('click', (event) => {
      const button = event.target instanceof Element ? event.target.closest('button') : null
      const card = button?.closest('[role="alert"]')
      if (!event.isTrusted || button?.textContent?.trim() !== 'Try again'
        || !card?.textContent?.includes("Couldn't load billing info")
        || !card.textContent.includes('Temporary pricing outage')) return
      const scope = window as Window & { __pricingRetryDispatches?: number }
      scope.__pricingRetryDispatches = (scope.__pricingRetryDispatches ?? 0) + 1
    }, true)
  })
  await page.route('**/subscription/plans', async (route) => {
    const retryDispatches = await page.evaluate(() => (window as Window & { __pricingRetryDispatches?: number }).__pricingRetryDispatches ?? 0)
    if (!retryDispatches) {
      outageRequests++
      return route.fulfill({ status: 503, json: { detail: 'Temporary pricing outage' } })
    }
    expect(route.request().headers().authorization).toBe('Bearer catalog-token')
    recoveredRequests++
    return route.fulfill({ json: {
      plans: makeCatalog().plans,
      billing: { provider: 'dodo', feature_enabled: true, mode: 'enabled', available: true, message: 'Billing available' },
    } })
  })
  const sessionResponse = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/auth/get-session' && response.status() === 200)
  const entitlementResponse = page.waitForResponse((response) => new URL(response.url()).pathname === '/config/entitlements'
    && new URL(response.url()).searchParams.get('include_quotas') === 'false'
    && response.request().headers().authorization === 'Bearer catalog-token' && response.status() === 200)
  await page.goto('/billing')
  expect((await (await sessionResponse).json()).user.id).toBe('catalog-admin')
  expect((await (await entitlementResponse).json()).features.i01).toBe(true)
  await expect(page.getByRole('button', { name: 'Open account menu' })).toBeVisible()
  const pricingError = page.getByRole('alert').filter({ hasText: "Couldn't load billing info" }).filter({ hasText: 'Temporary pricing outage' })
  await expect(pricingError).toBeVisible()
  expect(outageRequests).toBeGreaterThan(0)
  expect(recoveredRequests).toBe(0)
  const retryResponse = page.waitForResponse((response) => new URL(response.url()).pathname === '/subscription/plans' && response.status() === 200)
  await Promise.all([pricingError.getByRole('button', { name: 'Try again', exact: true }).click(), retryResponse])
  await expect(page.getByRole('heading', { name: 'Pro', exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as Window & { __pricingRetryDispatches?: number }).__pricingRetryDispatches ?? 0)).toBe(1)
  expect(recoveredRequests).toBe(1)
  await expect(page.getByText('10 / day').first()).toBeVisible()
  await page.getByRole('group', { name: 'Billing period' }).getByRole('button', { name: /^Annual\b/ }).click()
  await expect(page.getByRole('heading', { name: 'Pro Annual' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sales paused' })).toBeDisabled()
  await expect(page.getByRole('heading', { name: 'Pro', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Monthly', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Pro', exact: true })).toBeVisible()
})

test('admin saves catalog copy and sale pause with the current version', async ({ page }) => {
  await setup(page)
  const catalog = makeCatalog()
  await page.route('**/admin/plan-catalog', (route) => route.fulfill({ json: catalog }))
  const patches: Record<string, unknown>[] = []
  await page.route('**/admin/plan-catalog/pro', async (route) => {
    const update = route.request().postDataJSON()
    patches.push(update)
    Object.assign(catalog.plans.pro, update, { version: 2 })
    await route.fulfill({ json: catalog })
  })
  await page.goto('/admin')
  await page.getByRole('tab', { name: 'Plan Catalog' }).click()
  await page.getByLabel('Plan SKU').selectOption('pro')
  await expect(page.getByText('Configured price (read-only)')).toBeVisible()
  await page.getByLabel('Display name').fill('Professional')
  await page.getByLabel('Available for new purchases').uncheck()
  await page.getByRole('button', { name: 'Save plan' }).click()
  await expect(page.getByText('pro · version 2')).toBeVisible()
  expect(patches).toHaveLength(1)
  expect(patches[0]).toMatchObject({ version: 1, name: 'Professional', purchase_enabled: false })
  expect(patches[0]).not.toHaveProperty('price')
  await page.getByLabel('Plan SKU').selectOption('free')
  await expect(page.getByLabel('Available for new purchases')).toBeDisabled()
  await expect(page.getByLabel('Visible on pricing and billing')).toBeDisabled()
})

test('conflicting admin save keeps edits visible and supports reloading', async ({ page }) => {
  await setup(page)
  await page.route('**/admin/plan-catalog', (route) => route.fulfill({ json: makeCatalog() }))
  await page.route('**/admin/plan-catalog/pro', (route) => route.fulfill({ status: 409, json: { detail: 'This plan changed. Reload the catalog and review before saving again.' } }))
  await page.goto('/admin')
  await page.getByRole('tab', { name: 'Plan Catalog' }).click()
  await page.getByLabel('Plan SKU').selectOption('pro')
  await page.getByLabel('Display name').fill('Unsaved draft')
  await page.getByRole('button', { name: 'Save plan' }).click()
  await expect(page.getByRole('region', { name: 'Plan catalog' }).getByRole('alert')).toContainText('This plan changed')
  await expect(page.getByLabel('Display name')).toHaveValue('Unsaved draft')
  await page.getByRole('button', { name: 'Reload catalog' }).click()
  await expect(page.getByLabel('Display name')).toHaveValue('Pro')
})


test('admin changes quota limits without changing current usage windows', async ({ page }) => {
  await setup(page)
  const catalog = makeCatalog()
  await page.route('**/admin/plan-catalog', (route) => route.fulfill({ json: catalog }))
  const patches: Record<string, unknown>[] = []
  await page.route('**/admin/plan-catalog/free/quotas/compilations', async (route) => {
    const update = route.request().postDataJSON()
    patches.push(update)
    Object.assign(catalog.plans.free.quotas.compilations, update, { version: update.version + 1, source: 'admin_override' })
    await route.fulfill({ json: catalog })
  })
  await page.goto('/admin')
  await page.getByRole('tab', { name: 'Plan Catalog' }).click()
  await expect(page.getByText(/including existing subscribers/).last()).toBeVisible()
  await page.getByLabel('Request limit per day').fill('25')
  await page.getByRole('button', { name: 'Save quota limit' }).click()
  await expect(page.getByText('Fixed reset window: day. Version 2. Admin override.')).toBeVisible()
  expect(patches[0]).toEqual({ version: 1, limit: 25 })
  await page.getByLabel('Unlimited allowance').check()
  await expect(page.getByLabel('Request limit per day')).toBeDisabled()
  await page.getByRole('button', { name: 'Save quota limit' }).click()
  await expect(page.getByText('Fixed reset window: day. Version 3. Admin override.')).toBeVisible()
  expect(patches[1]).toEqual({ version: 2, limit: null })
})
