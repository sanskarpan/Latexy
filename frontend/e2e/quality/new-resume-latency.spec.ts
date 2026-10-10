import { expect, test } from '@playwright/test'
import { mockEngineAncillaryApi } from './engine-fixtures'

test('resume title and import controls remain usable while template requests are pending', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('latexy_onboarding_completed', 'true'))
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  await mockEngineAncillaryApi(page, 'latency-test')
  let templateRequests = 0
  await page.route(url => url.pathname === '/templates' || url.pathname.startsWith('/templates/'), route => {
    if (!['fetch', 'xhr'].includes(route.request().resourceType())
      || route.request().headers().rsc === '1') return route.fallback()
    templateRequests++
    return pending.then(() => route.fulfill({ json: [] }))
  })
  await page.route('**/api/auth/get-session', route => route.fulfill({ json: {
    session: { token: 'latency-test-token' }, user: { id: 'latency-test', email: 'latency@example.com', name: 'Latency QA', emailVerified: true },
  } }))
  try {
    await page.goto('/workspace/new', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Create Resume', exact: true })).toBeVisible({ timeout: 10000 })
    await page.locator('#new-resume-title').fill('Resume without waiting for templates')
    await expect(page.getByRole('button', { name: /^Import File/ })).toBeEnabled()
    await expect.poll(() => templateRequests).toBeGreaterThan(0)
    await expect(page.getByRole('status', { name: 'Loading templates' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start from Blank', exact: true })).toBeEnabled()
  } finally { release() }
  await expect(page.getByRole('status', { name: 'Loading templates' })).toHaveCount(0)
})
