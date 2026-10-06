import { test, expect, type Page } from '@playwright/test'

const SESSION = {
  session: { token: 'mock-token' },
  user: { id: 'tracker-user', email: 'tracker@example.com', name: 'Tracker User' },
}

const application = (id: string, company: string, role: string) => ({
  id,
  user_id: 'tracker-user',
  company_name: company,
  role_title: role,
  status: 'applied',
  resume_id: null,
  ats_score_at_submission: null,
  job_description_text: null,
  job_url: null,
  company_logo_url: null,
  notes: null,
  applied_at: '2026-10-03T00:00:00Z',
  updated_at: '2026-10-03T00:00:00Z',
  created_at: '2026-10-03T00:00:00Z',
})

async function mockOwnershipSwitch(page: Page, oldApp: ReturnType<typeof application>, newApp: ReturnType<typeof application>, onDelete: () => void) {
  let owner: 'old' | 'new' = 'old'
  await page.route('**/api/auth/get-session', (route) => {
    const session = owner === 'old'
      ? SESSION
      : { session: { token: 'mock-token-b' }, user: { id: 'tracker-user-b', email: 'b@example.com', name: 'User B' } }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(session) })
  })
  await page.route((url) => {
    const path = url.pathname
    return path === '/tracker/applications' || path === '/tracker/stale-applications'
  }, (route) => {
    if (route.request().url().includes('/stale-applications')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    const currentApp = owner === 'old' ? oldApp : newApp
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ by_status: { applied: [currentApp] } }),
    })
  })
  await page.route((url) => url.pathname === `/tracker/applications/${oldApp.id}`, async (route) => {
    onDelete()
    await route.fulfill({ status: 204 })
  })
  await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText(oldApp.company_name, { exact: true })).toBeVisible()
  return async () => {
    owner = 'new'
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
    await expect(page.getByText(newApp.company_name, { exact: true })).toBeVisible()
  }
}

test('diagnostic: failed deferred delete must not roll back a newer board mutation', async ({ page }) => {
  const acme = application('app-acme', 'Acme Corp', 'Senior Engineer')
  const beta = application('app-beta', 'Beta Labs', 'Platform Engineer')
  let deleteFinished = false

  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) })
  )
  await page.route((url) => {
    const path = url.pathname
    return path === '/tracker/applications' || path === '/tracker/stale-applications'
  }, async (route) => {
    if (route.request().method() === 'GET' && route.request().url().includes('/stale-applications')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ by_status: { applied: [acme, beta] } }),
    })
  })
  await page.route((url) => url.pathname === '/tracker/applications/app-beta/status', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...beta, status: 'phone_screen' }) })
  )
  await page.route((url) => url.pathname === '/tracker/applications/app-acme', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic delete failure' }) }).then(() => {
      deleteFinished = true
    })
  )

  await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Acme Corp', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Actions for Acme Corp' }).click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()

  // A newer optimistic mutation occurs while the deferred delete is pending.
  await page.getByLabel('Move Beta Labs to status').selectOption('phone_screen')
  await expect(page.getByLabel('Move Beta Labs to status')).toHaveValue('phone_screen')

  // Delete is intentionally deferred by the implementation for five seconds.
  await page.waitForTimeout(5_250)
  await expect.poll(() => deleteFinished).toBe(true)

  // The failed delete restores Acme without reverting Beta's newer mutation.
  await expect(page.getByLabel('Move Beta Labs to status')).toHaveValue('phone_screen')
})

test('positive control: same-owner deferred delete can be undone before commit', async ({ page }) => {
  const acme = application('app-acme', 'Acme Corp', 'Senior Engineer')
  let deleteCalled = false

  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) })
  )
  await page.route((url) => {
    const path = url.pathname
    return path === '/tracker/applications' || path === '/tracker/stale-applications'
  }, (route) => {
    if (route.request().url().includes('/stale-applications')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ by_status: { applied: [acme] } }),
    })
  })
  await page.route((url) => url.pathname === '/tracker/applications/app-acme', async (route) => {
    deleteCalled = true
    await route.fulfill({ status: 204 })
  })

  await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Acme Corp', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Actions for Acme Corp' }).click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()
  await expect(page.getByRole('button', { name: 'Undo' })).toBeVisible()
  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(page.getByText('Acme Corp', { exact: true })).toBeVisible()

  await page.waitForTimeout(5_250)
  expect(deleteCalled).toBe(false)
  await expect(page.getByText('Acme Corp', { exact: true })).toBeVisible()
})

test('positive control: same-owner deferred delete removes the card after success', async ({ page }) => {
  const acme = application('app-acme', 'Acme Corp', 'Senior Engineer')
  let deleteCalled = false

  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) })
  )
  await page.route((url) => {
    const path = url.pathname
    return path === '/tracker/applications' || path === '/tracker/stale-applications'
  }, (route) => {
    if (route.request().url().includes('/stale-applications')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ by_status: { applied: [acme] } }),
    })
  })
  await page.route((url) => url.pathname === '/tracker/applications/app-acme', async (route) => {
    deleteCalled = true
    await route.fulfill({ status: 204 })
  })

  await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Acme Corp', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Actions for Acme Corp' }).click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()
  await page.waitForTimeout(5_250)

  expect(deleteCalled).toBe(true)
  await expect(page.getByText('Acme Corp', { exact: true })).toHaveCount(0)
})

test('owner switch: deferred delete does not issue the old-user DELETE request', async ({ page }) => {
  const acme = application('app-acme', 'Acme Corp', 'Senior Engineer')
  const beta = application('app-beta', 'Beta Labs', 'Platform Engineer')
  let deleteCalled = false
  const switchOwner = await mockOwnershipSwitch(page, acme, beta, () => { deleteCalled = true })

  await page.getByRole('button', { name: 'Actions for Acme Corp' }).click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()
  await page.waitForTimeout(500)
  await switchOwner()
  await page.waitForTimeout(5_250)

  expect(deleteCalled).toBe(false)
  await expect(page.getByText('Acme Corp', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Beta Labs', { exact: true })).toBeVisible()
})

test('owner switch: stale Undo does not restore an old-user card into the new board', async ({ page }) => {
  const acme = application('app-acme', 'Acme Corp', 'Senior Engineer')
  const beta = application('app-beta', 'Beta Labs', 'Platform Engineer')
  let deleteCalled = false
  const switchOwner = await mockOwnershipSwitch(page, acme, beta, () => { deleteCalled = true })

  await page.getByRole('button', { name: 'Actions for Acme Corp' }).click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()
  await page.waitForTimeout(500)
  await switchOwner()
  await page.getByRole('button', { name: 'Undo' }).click()

  expect(deleteCalled).toBe(false)
  await expect(page.getByText('Acme Corp', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Beta Labs', { exact: true })).toBeVisible()
})

test('diagnostic: failed status PATCH must not roll back a newer same-card status', async ({ page }) => {
  const acme = application('app-acme', 'Acme Corp', 'Senior Engineer')
  let statusCalls = 0
  let firstFinished = false
  let releaseFirst!: () => void
  let firstSeen!: () => void
  const firstRequest = new Promise<void>((resolve) => { firstSeen = resolve })

  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) })
  )
  await page.route((url) => url.pathname === '/tracker/applications' || url.pathname === '/tracker/stale-applications', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(route.request().url().includes('/stale-applications') ? [] : { by_status: { applied: [acme] } }),
    })
  )
  await page.route((url) => url.pathname === '/tracker/applications/app-acme/status', async (route) => {
    statusCalls += 1
    if (statusCalls === 1) {
      firstSeen()
      await new Promise<void>((resolve) => { releaseFirst = resolve })
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic status failure' }) })
      firstFinished = true
      return
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...acme, status: 'technical' }) })
  })

  await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Acme Corp', { exact: true })).toBeVisible()
  const status = page.getByLabel('Move Acme Corp to status')
  await status.selectOption('phone_screen')
  await firstRequest
  await status.selectOption('technical')
  await expect.poll(() => statusCalls).toBe(2)
  releaseFirst()
  await expect.poll(() => firstFinished).toBe(true)

  // Expected red before per-application mutation sequencing is added.
  await expect(status).toHaveValue('technical')
})

test('diagnostic: failed status PATCH must preserve another card mutation', async ({ page }) => {
  const acme = application('app-acme', 'Acme Corp', 'Senior Engineer')
  const beta = application('app-beta', 'Beta Labs', 'Platform Engineer')
  let releaseFirst!: () => void
  let firstSeen!: () => void
  let firstFinished = false
  const firstRequest = new Promise<void>((resolve) => { firstSeen = resolve })

  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) })
  )
  await page.route((url) => url.pathname === '/tracker/applications' || url.pathname === '/tracker/stale-applications', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(route.request().url().includes('/stale-applications') ? [] : { by_status: { applied: [acme, beta] } }),
    })
  )
  await page.route((url) => url.pathname.endsWith('/status'), async (route) => {
    if (route.request().url().includes('app-acme')) {
      firstSeen()
      await new Promise<void>((resolve) => { releaseFirst = resolve })
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic status failure' }) })
      firstFinished = true
      return
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...beta, status: 'phone_screen' }) })
  })

  await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Acme Corp', { exact: true })).toBeVisible()
  const acmeStatus = page.getByLabel('Move Acme Corp to status')
  const betaStatus = page.getByLabel('Move Beta Labs to status')
  await acmeStatus.selectOption('phone_screen')
  await firstRequest
  await betaStatus.selectOption('technical')
  await expect(betaStatus).toHaveValue('technical')
  releaseFirst()
  await expect.poll(() => firstFinished).toBe(true)

  // Expected red before the catch is changed from whole-board restoration.
  await expect(betaStatus).toHaveValue('technical')
})

test('diagnostic: failed old-owner status PATCH must not restore into a new board', async ({ page }) => {
  const acme = application('app-acme', 'Acme Corp', 'Senior Engineer')
  const beta = application('app-beta', 'Beta Labs', 'Platform Engineer')
  let owner: 'old' | 'new' = 'old'
  let releaseFirst!: () => void
  let firstSeen!: () => void
  let firstFinished = false
  const firstRequest = new Promise<void>((resolve) => { firstSeen = resolve })

  await page.route('**/api/auth/get-session', (route) => {
    const session = owner === 'old'
      ? SESSION
      : { session: { token: 'mock-token-b' }, user: { id: 'tracker-user-b', email: 'b@example.com', name: 'User B' } }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(session) })
  })
  await page.route((url) => url.pathname === '/tracker/applications' || url.pathname === '/tracker/stale-applications', (route) => {
    if (route.request().url().includes('/stale-applications')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    const current = owner === 'old' ? acme : beta
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ by_status: { applied: [current] } }) })
  })
  await page.route((url) => url.pathname === '/tracker/applications/app-acme/status', async (route) => {
    firstSeen()
    await new Promise<void>((resolve) => { releaseFirst = resolve })
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic status failure' }) })
    firstFinished = true
    return
  })

  await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Acme Corp', { exact: true })).toBeVisible()
  await page.getByLabel('Move Acme Corp to status').selectOption('phone_screen')
  await firstRequest
  owner = 'new'
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
  await expect(page.getByText('Beta Labs', { exact: true })).toBeVisible()
  releaseFirst()
  await expect.poll(() => firstFinished).toBe(true)

  // Expected red before owner-aware status rollback is added.
  await expect(page.getByText('Acme Corp', { exact: true })).toHaveCount(0)
})

test('diagnostic: stale status failure cannot resurrect a newer deleted card', async ({ page }) => {
  const acme = application('app-acme', 'Acme Corp', 'Senior Engineer')
  let releaseStatus!: () => void
  let statusFinished = false
  let statusSeen!: () => void
  const statusRequest = new Promise<void>((resolve) => { statusSeen = resolve })

  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) })
  )
  await page.route((url) => url.pathname === '/tracker/applications' || url.pathname === '/tracker/stale-applications', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(route.request().url().includes('/stale-applications') ? [] : { by_status: { applied: [acme] } }),
    })
  )
  await page.route((url) => url.pathname === '/tracker/applications/app-acme/status', async (route) => {
    statusSeen()
    await new Promise<void>((resolve) => { releaseStatus = resolve })
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic status failure' }) })
    statusFinished = true
  })
  await page.route((url) => url.pathname === '/tracker/applications/app-acme', (route) =>
    route.fulfill({ status: 204 })
  )

  await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Acme Corp', { exact: true })).toBeVisible()
  await page.getByLabel('Move Acme Corp to status').selectOption('phone_screen')
  await statusRequest
  await page.getByRole('button', { name: 'Actions for Acme Corp' }).click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()
  await expect(page.getByText('Acme Corp', { exact: true })).toHaveCount(0)
  releaseStatus()
  await expect.poll(() => statusFinished).toBe(true)

  // Expected red before the current-app/status guard is added.
  await expect(page.getByText('Acme Corp', { exact: true })).toHaveCount(0)
})

test('positive control: failed same-owner status restores its original position', async ({ page }) => {
  const acme = application('app-acme', 'Acme Corp', 'Senior Engineer')
  const gamma = application('app-gamma', 'Gamma Inc', 'Staff Engineer')
  let releaseStatus!: () => void
  let statusFinished = false
  let statusSeen!: () => void
  const statusRequest = new Promise<void>((resolve) => { statusSeen = resolve })

  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) })
  )
  await page.route((url) => url.pathname === '/tracker/applications' || url.pathname === '/tracker/stale-applications', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(route.request().url().includes('/stale-applications') ? [] : { by_status: { applied: [acme, gamma] } }),
    })
  )
  await page.route((url) => url.pathname === '/tracker/applications/app-acme/status', async (route) => {
    statusSeen()
    await new Promise<void>((resolve) => { releaseStatus = resolve })
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic status failure' }) })
    statusFinished = true
  })

  await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Acme Corp', { exact: true })).toBeVisible()
  await page.getByLabel('Move Acme Corp to status').selectOption('phone_screen')
  await statusRequest
  releaseStatus()
  await expect.poll(() => statusFinished).toBe(true)

  await expect(page.getByLabel('Move Acme Corp to status')).toHaveValue('applied')
  // Applied cards retain their pre-mutation order: Acme was originally first.
  await expect(page.locator('select[id^="status-"]').first()).toHaveAttribute('id', 'status-app-acme')
})
