import { expect, test } from '@playwright/test'

test('resume title and import controls remain usable while template requests are pending', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('latexy_onboarding_completed', 'true'))
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  await page.route(/(?:https?:\/\/(localhost|127\.0\.0\.1):(8030|8530)|https:\/\/sanskarpandey2004--latexy-backend-fastapi-app\.modal\.run)\/.*$/, route => {
    const path = new URL(route.request().url()).pathname
    if (path.startsWith('/templates')) return pending.then(() => route.fulfill({ json: [] }))
    if (path === '/me') return route.fulfill({ json: { id: 'latency-test', preferences: { has_onboarded: true } } })
    if (path.startsWith('/config/entitlements')) return route.fulfill({ json: {} })
    return route.fulfill({ json: {} })
  })
  await page.route('**/api/auth/get-session', route => route.fulfill({ json: {
    session: { token: 'latency-test-token' }, user: { id: 'latency-test', email: 'latency@example.com', name: 'Latency QA', emailVerified: true },
  } }))
  try {
    await page.goto('/workspace/new', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Create Resume', exact: true })).toBeVisible({ timeout: 10000 })
    await page.locator('#new-resume-title').fill('Resume without waiting for templates')
    await expect(page.getByRole('button', { name: /^Import File/ })).toBeEnabled()
    await expect(page.getByRole('status', { name: 'Loading templates' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start from Blank', exact: true })).toBeEnabled()
  } finally { release() }
  await expect(page.getByRole('status', { name: 'Loading templates' })).toHaveCount(0)
})
