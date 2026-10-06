import { expect, test, type Page } from '@playwright/test'

const SESSION_A = {
  session: { token: 'tracker-panel-owner-a-token' },
  user: { id: 'tracker-panel-owner-a', email: 'panel-a@example.com', name: 'Panel Owner A' },
}
const SESSION_B = {
  session: { token: 'tracker-panel-owner-b-token' },
  user: { id: 'tracker-panel-owner-b', email: 'panel-b@example.com', name: 'Panel Owner B' },
}

const savedJob = (owner: 'A' | 'B') => ({
  id: `saved-panel-${owner}`,
  company_name: `Panel Company ${owner}`,
  role_title: `Panel Designer ${owner}`,
  job_url: null,
  job_description_text: null,
  notes: null,
  created_at: '2026-10-04T00:00:00Z',
  updated_at: '2026-10-04T00:00:00Z',
})

const alert = (owner: 'A' | 'B') => ({
  id: `alert-panel-${owner}`,
  query: `Panel query ${owner}`,
  company_name: null,
  location: null,
  source_url: 'https://example.invalid/search',
  frequency: 'daily',
  active: true,
  last_notified_at: null,
  created_at: '2026-10-04T00:00:00Z',
  updated_at: '2026-10-04T00:00:00Z',
})

const contact = (owner: 'A' | 'B') => ({
  id: `contact-panel-${owner}`,
  company_id: null,
  name: `Panel Contact ${owner}`,
  role_title: 'Recruiter',
  email: `contact-${owner.toLowerCase()}@example.invalid`,
  phone: null,
  linkedin_url: null,
  notes: null,
  created_at: '2026-10-04T00:00:00Z',
  updated_at: '2026-10-04T00:00:00Z',
})

async function setup(page: Page, ownerRef: { current: 'a' | 'b' }) {
  let sessionCalls = 0
  await page.addInitScript(() => localStorage.setItem('latexy_onboarding_completed', 'true'))
  await page.route('**/api/auth/get-session', (route) => {
    sessionCalls += 1
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(ownerRef.current === 'a' ? SESSION_A : SESSION_B),
    })
  })
  await page.route((url) => url.pathname === '/tracker/applications', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ by_status: { applied: [], phone_screen: [], technical: [], onsite: [], offer: [], rejected: [], withdrawn: [] } }) }))
  await page.route((url) => url.pathname === '/tracker/stats', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total_applications: 0, by_status: {}, avg_ats_score: null, applications_this_week: 0, applications_this_month: 0, response_rate: 0, offer_rate: 0 }) }))
  await page.route((url) => url.pathname === '/tracker/stale-applications', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route('**/ws/**', (route) => route.abort())
  return {
    switchOwner: async (nextOwner: 'a' | 'b') => {
      ownerRef.current = nextOwner
      await page.evaluate(() => {
        const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
        localStorage.setItem('better-auth.message', message)
        window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
      })
      await expect.poll(() => sessionCalls).toBeGreaterThan(1)
    },
  }
}

async function settle(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50))))
  )
}

test.describe('tracker auxiliary panel ownership diagnostics', () => {
  test('saved jobs do not apply a deferred old-owner response', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership diagnostic runs against the production bundle')
    const ownerRef: { current: 'a' | 'b' } = { current: 'a' }
    const workspace = await setup(page, ownerRef)
    let releaseA!: () => void
    let startedA!: () => void
    const gateA = new Promise<void>((resolve) => { releaseA = resolve })
    const requestA = new Promise<void>((resolve) => { startedA = resolve })
    await page.route((url) => url.pathname === '/tracker/saved-jobs', async (route) => {
      if (ownerRef.current === 'a') {
        startedA()
        await gateA
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([savedJob('A')]) })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([savedJob('B')]) })
    })

    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Saved jobs' }).click()
    await requestA
    await workspace.switchOwner('b')
    const oldResponse = page.waitForResponse((response) => response.url().includes('/tracker/saved-jobs') && response.status() === 200)
    releaseA()
    const response = await oldResponse
    await response.finished()
    await settle(page)
    await expect(page.getByText('Panel Designer A', { exact: true })).toHaveCount(0)
  })

  test('same-owner saved jobs response remains visible', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership diagnostic runs against the production bundle')
    const ownerRef: { current: 'a' | 'b' } = { current: 'a' }
    await setup(page, ownerRef)
    let release!: () => void
    let started!: () => void
    const gate = new Promise<void>((resolve) => { release = resolve })
    const requestStarted = new Promise<void>((resolve) => { started = resolve })
    await page.route((url) => url.pathname === '/tracker/saved-jobs', async (route) => {
      started()
      await gate
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([savedJob('A')]) })
    })
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Saved jobs' }).click()
    await requestStarted
    const responsePromise = page.waitForResponse((response) => response.url().includes('/tracker/saved-jobs') && response.status() === 200)
    release()
    const response = await responsePromise
    await response.finished()
    await settle(page)
    await expect(page.getByText('Panel Designer A', { exact: true })).toBeVisible()
  })

  test('alerts do not apply a deferred old-owner response', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership diagnostic runs against the production bundle')
    const ownerRef: { current: 'a' | 'b' } = { current: 'a' }
    const workspace = await setup(page, ownerRef)
    let releaseA!: () => void
    let startedA!: () => void
    const gateA = new Promise<void>((resolve) => { releaseA = resolve })
    const requestA = new Promise<void>((resolve) => { startedA = resolve })
    await page.route((url) => url.pathname === '/tracker/alerts', async (route) => {
      if (ownerRef.current === 'a') {
        startedA()
        await gateA
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([alert('A')]) })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([alert('B')]) })
    })
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Alerts' }).click()
    await requestA
    await workspace.switchOwner('b')
    const oldResponse = page.waitForResponse((response) => response.url().includes('/tracker/alerts') && response.status() === 200)
    releaseA()
    const response = await oldResponse
    await response.finished()
    await settle(page)
    await expect(page.getByText('Panel query A', { exact: true })).toHaveCount(0)
  })

  test('contacts do not apply a deferred old-owner response', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership diagnostic runs against the production bundle')
    const ownerRef: { current: 'a' | 'b' } = { current: 'a' }
    const workspace = await setup(page, ownerRef)
    let releaseA!: () => void
    let startedA!: () => void
    const gateA = new Promise<void>((resolve) => { releaseA = resolve })
    const requestA = new Promise<void>((resolve) => { startedA = resolve })
    await page.route((url) => url.pathname === '/tracker/contacts', async (route) => {
      if (ownerRef.current === 'a') {
        startedA()
        await gateA
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([contact('A')]) })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([contact('B')]) })
    })
    await page.route((url) => url.pathname === '/tracker/companies', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Contacts' }).click()
    await requestA
    await workspace.switchOwner('b')
    const oldResponse = page.waitForResponse((response) => response.url().includes('/tracker/contacts') && response.status() === 200)
    releaseA()
    const response = await oldResponse
    await response.finished()
    await settle(page)
    await expect(page.getByText('Panel Contact A', { exact: true })).toHaveCount(0)
  })
})
