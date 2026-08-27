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
  await page.route('**/github/status', disconnected)
}

const PROVIDERS = [
  {
    name: 'Zotero',
    path: 'zotero',
    success: 'Zotero connected successfully!',
    status: { connected: true, username: 'bound-user', user_id: 'zotero-1' },
    connectedText: '@bound-user',
  },
  {
    name: 'Mendeley',
    path: 'mendeley',
    success: 'Mendeley connected successfully!',
    status: { connected: true, name: 'Bound User' },
    connectedText: 'Bound User',
  },
  {
    name: 'Dropbox',
    path: 'dropbox',
    success: 'Dropbox connected successfully!',
    status: { connected: true, display_name: 'Bound User', account_id: 'dropbox-1' },
    connectedText: 'Dropbox connected',
  },
] as const

for (const provider of PROVIDERS) {
  test(`${provider.name} OAuth starts and completes through authenticated one-time requests`, async ({ page }) => {
    await mockSettingsDependencies(page, SESSION)
    let connected = false
    let completionCalls = 0

    for (const other of PROVIDERS) {
      await page.route(`**/${other.path}/status`, (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(
            other.path === provider.path && connected
              ? provider.status
              : { connected: false }
          ),
        })
      )
    }
    await page.route(`**/${provider.path}/connect`, async (route) => {
      expect(route.request().method()).toBe('POST')
      expect(await route.request().headerValue('authorization')).toBe(
        'Bearer latexy-session'
      )
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          authorization_url: `${new URL(page.url()).origin}/settings?${provider.path}=complete&ticket=one-time-ticket`,
        }),
      })
    })
    await page.route(`**/${provider.path}/complete`, async (route) => {
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
        body: JSON.stringify({ success: true, message: `${provider.name} connected` }),
      })
    })

    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    const connect = page.getByRole('button', { name: `Connect ${provider.name}` })
    await expect(connect).toBeVisible()
    await connect.click()

    await expect(page.getByText(provider.success)).toBeVisible()
    await expect(page.getByText(provider.connectedText, { exact: true })).toBeVisible()
    await expect(page).toHaveURL(/\/settings$/)
    expect(completionCalls).toBe(1)
  })
}

test('a signed-out browser never submits a provider completion ticket', async ({ page }) => {
  await mockSettingsDependencies(page, null)
  let completionCalls = 0
  await page.route('**/dropbox/complete', (route) => {
    completionCalls += 1
    return route.fulfill({ status: 500, body: 'must not be called' })
  })

  await page.goto('/settings?dropbox=complete&ticket=attacker-ticket', {
    waitUntil: 'domcontentloaded',
  })

  await expect(page.getByText('Sign in to manage settings')).toBeVisible()
  await expect(page).toHaveURL(/\/settings$/)
  expect(completionCalls).toBe(0)
})
