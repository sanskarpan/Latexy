import { expect, test, type Page, type Route } from '@playwright/test'

const SESSION = {
  session: { id: 'session-1', userId: 'user-1', token: 'latexy-session' },
  user: { id: 'user-1', email: 'user@example.com', name: 'OAuth User' },
}

async function mockSettingsDependencies(page: Page, session: typeof SESSION | null) {
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(session),
    })
  )
  await page.route('**/settings/notifications', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ job_completed: true, weekly_digest: false }),
    })
  )
  const disconnected = (route: Route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ connected: false }),
  })
  await page.route('**/zotero/status', disconnected)
  await page.route('**/mendeley/status', disconnected)
  await page.route('**/dropbox/status', disconnected)
}

test('GitHub OAuth starts and completes through authenticated one-time requests', async ({ page }) => {
  await mockSettingsDependencies(page, SESSION)
  let connected = false
  let completionCalls = 0

  await page.route('**/github/status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        connected,
        username: connected ? 'bound-user' : null,
      }),
    })
  )
  await page.route((url) => url.pathname === '/github/connect', async (route) => {
    expect(route.request().method()).toBe('POST')
    expect(await route.request().headerValue('authorization')).toBe(
      'Bearer latexy-session'
    )
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        authorization_url: `${new URL(page.url()).origin}/settings?github=complete&ticket=one-time-ticket`,
      }),
    })
  })
  await page.route('**/github/complete', async (route) => {
    completionCalls += 1
    expect(route.request().method()).toBe('POST')
    expect(await route.request().headerValue('authorization')).toBe(
      'Bearer latexy-session'
    )
    expect(route.request().postDataJSON()).toEqual({ ticket: 'one-time-ticket' })
    connected = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'GitHub account connected' }),
    })
  })

  await page.goto('/settings', { waitUntil: 'domcontentloaded' })
  const connect = page.getByRole('button', { name: 'Connect GitHub' })
  await expect(connect).toBeVisible()
  await connect.click()

  await expect(page.getByText('GitHub account connected successfully!')).toBeVisible()
  await expect(page.getByText('bound-user')).toBeVisible()
  await expect(page).toHaveURL(/\/settings$/)
  expect(completionCalls).toBe(1)
})

test('a signed-out browser never submits someone else’s completion ticket', async ({ page }) => {
  await mockSettingsDependencies(page, null)
  let completionCalls = 0
  await page.route('**/github/complete', (route) => {
    completionCalls += 1
    return route.fulfill({ status: 500, body: 'must not be called' })
  })

  await page.goto('/settings?github=complete&ticket=attacker-ticket', {
    waitUntil: 'domcontentloaded',
  })

  await expect(page.getByText('Sign in to manage settings')).toBeVisible()
  await expect(page).toHaveURL(/\/settings$/)
  expect(completionCalls).toBe(0)
})
