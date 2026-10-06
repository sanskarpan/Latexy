import { expect, test, type Page } from '@playwright/test'

const SESSION_A = {
  session: { token: 'tracker-refresh-owner-a-token' },
  user: { id: 'tracker-refresh-owner-a', email: 'refresh-a@example.com', name: 'Refresh Owner A' },
}
const SESSION_B = {
  session: { token: 'tracker-refresh-owner-b-token' },
  user: { id: 'tracker-refresh-owner-b', email: 'refresh-b@example.com', name: 'Refresh Owner B' },
}

const savedJob = (owner: 'A' | 'B') => ({
  id: `saved-refresh-${owner}`,
  company_name: `Refresh Company ${owner}`,
  role_title: `Refresh Role ${owner}`,
  job_url: null,
  job_description_text: null,
  notes: null,
  created_at: '2026-10-04T00:00:00Z',
  updated_at: '2026-10-04T00:00:00Z',
})

async function setup(page: Page, ownerRef: { current: 'a' | 'b' }, authRef: { mode: 'ok' | 'error'; calls: number }) {
  await page.addInitScript(() => localStorage.setItem('latexy_onboarding_completed', 'true'))
  await page.route('**/api/auth/get-session', (route) => {
    authRef.calls += 1
    if (authRef.mode === 'error') return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'session temporarily unavailable' }) })
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ownerRef.current === 'a' ? SESSION_A : SESSION_B) })
  })
  await page.route((url) => url.pathname === '/tracker/applications', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ by_status: { applied: [], phone_screen: [], technical: [], onsite: [], offer: [], rejected: [], withdrawn: [] } }) }))
  await page.route((url) => url.pathname === '/tracker/stats', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total_applications: 0, by_status: {}, avg_ats_score: null, applications_this_week: 0, applications_this_month: 0, response_rate: 0, offer_rate: 0 }) }))
  await page.route((url) => url.pathname === '/tracker/stale-applications', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((url) => url.pathname === '/tracker/saved-jobs', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([savedJob(ownerRef.current === 'a' ? 'A' : 'B')]) }))
  await page.route('**/ws/**', (route) => route.abort())
}

async function refreshSession(page: Page) {
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
}

async function refreshSessionAndSettle(page: Page) {
  const responsePromise = page.waitForResponse((response) => response.url().includes('/api/auth/get-session'))
  await refreshSession(page)
  const response = await responsePromise
  await response.finished()
  await settle(page)
}

async function settle(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 80))))
  )
}

test.describe('tracker saved-job refresh persistence policy', () => {
  test('same-owner verified refresh keeps the clean saved-job panel', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'refresh persistence policy runs against the production bundle')
    const ownerRef: { current: 'a' | 'b' } = { current: 'a' }
    const authRef = { mode: 'ok' as const, calls: 0 }
    await setup(page, ownerRef, authRef)
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Saved jobs' }).click()
    await expect(page.getByText('Refresh Role A', { exact: true })).toBeVisible()
    await refreshSessionAndSettle(page)
    await expect(page.getByText('Refresh Role A', { exact: true })).toBeVisible()
  })

  test('same-owner refresh and final session error preserve a dirty saved-job form', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'refresh persistence policy runs against the production bundle')
    const ownerRef: { current: 'a' | 'b' } = { current: 'a' }
    const authRef = { mode: 'ok' as 'ok' | 'error', calls: 0 }
    await setup(page, ownerRef, authRef)
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Saved jobs' }).click()
    await page.getByLabel('Company').fill('Unsaved Refresh Company')
    await page.getByLabel('Role title').fill('Unsaved Refresh Role')

    await refreshSessionAndSettle(page)
    await expect(page.getByLabel('Company')).toHaveValue('Unsaved Refresh Company')
    await expect(page.getByLabel('Role title')).toHaveValue('Unsaved Refresh Role')

    authRef.mode = 'error'
    await refreshSessionAndSettle(page)
    await expect(page.getByLabel('Company')).toHaveValue('Unsaved Refresh Company')
    await expect(page.getByLabel('Role title')).toHaveValue('Unsaved Refresh Role')
    await expect(page.getByText('Refresh Role A', { exact: true })).toBeVisible()
  })

  test('owner switch does not expose a dirty form to the next account', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'refresh persistence policy runs against the production bundle')
    const ownerRef: { current: 'a' | 'b' } = { current: 'a' }
    const authRef = { mode: 'ok' as const, calls: 0 }
    await setup(page, ownerRef, authRef)
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Saved jobs' }).click()
    await page.getByLabel('Company').fill('Private Owner A Draft')
    await page.getByLabel('Role title').fill('Private Owner A Role')

    ownerRef.current = 'b'
    await refreshSessionAndSettle(page)
    await expect(page.getByText('Refresh Role B', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Company')).toHaveValue('')
    await expect(page.getByLabel('Role title')).toHaveValue('')
    await expect(page.getByText('Private Owner A Draft', { exact: true })).toHaveCount(0)
  })
})
