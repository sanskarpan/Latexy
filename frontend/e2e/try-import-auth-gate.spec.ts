import { expect, test, type Page } from '@playwright/test'

test.setTimeout(60_000)

async function mockIdleWebSocket(page: Page) {
  await page.routeWebSocket('**/ws/jobs**', (ws) => {
    ws.onMessage((data) => {
      try {
        const message = JSON.parse(data as string)
        if (message.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
        }
      } catch {
        /* ignore malformed client frames in this idle transport */
      }
    })
  })
}

async function mockAnonymousTry(page: Page) {
  await mockIdleWebSocket(page)
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: 'null' })
  )
  await page.route('**/config/feature-flags', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  )
  await page.route('**/public/trial-status?*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ usageCount: 0, trialLimit: 3, blocked: false }),
    })
  )
}

async function openImportPanel(page: Page) {
  await page.goto('/try', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('button', { name: /recompile/i })).toBeVisible()
  // The controls are server-rendered before their event handlers hydrate.
  // Autosave runs only after hydration and is a stable readiness signal.
  await expect.poll(() => page.evaluate(() => localStorage.getItem('latexy_try_latex'))).not.toBeNull()
  await page.locator('nav button[title="Import"]').click()
}

test.describe('anonymous /try import authentication gate', () => {
  test.describe.configure({ mode: 'serial' })

  test('project imports preserve the draft and go to login without a protected API call', async ({ page }) => {
    await mockAnonymousTry(page)
    const protectedRequests: string[] = []
    page.on('request', (request) => {
      if (/\/(github\/(status|import-projects)|sources\/import-(url|linkedin))/.test(request.url())) {
        protectedRequests.push(request.url())
      }
    })

    await openImportPanel(page)
    const login = page.getByRole('button', { name: /log in to import projects/i })
    await expect(login).toBeEnabled()
    await login.click()

    await expect(page).toHaveURL(/\/login\?redirect=/)
    expect(new URL(page.url()).searchParams.get('redirect')).toBe('/try')
    expect(await page.evaluate(() => localStorage.getItem('latexy_try_latex'))).toContain('\\documentclass')
    expect(protectedRequests).toEqual([])
  })

  test('existing-file import stays local and rejects server-backed formats before upload', async ({ page }) => {
    await mockAnonymousTry(page)
    const protectedRequests: string[] = []
    page.on('request', (request) => {
      if (/\/(formats\/upload|sources\/import-linkedin)/.test(request.url())) {
        protectedRequests.push(request.url())
      }
    })

    await openImportPanel(page)
    await page.getByRole('button', { name: /existing file/i }).click()

    await expect(page.getByText('Upload LaTeX Source')).toBeVisible()
    const input = page.locator('input[type="file"]')
    await expect(input).toHaveAttribute('accept', '.tex,.latex,.ltx')
    await input.setInputFiles({
      name: 'resume.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 test'),
    })

    await expect(page.getByText(/Log in to convert PDF, Word, image/i)).toBeVisible()
    expect(protectedRequests).toEqual([])
    await expect(page.getByRole('button', { name: /log in and return here/i })).toBeVisible()
  })

  test('authenticated visitors retain the connected-source import flow', async ({ page }) => {
    await mockIdleWebSocket(page)
    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session: { id: 'session-1', userId: 'user-1', token: 'test-token' },
          user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
        }),
      })
    )
    await page.route('**/config/feature-flags', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    )
    await page.route('**/public/trial-status?*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ usageCount: 0, trialLimit: 3, blocked: false }),
      })
    )

    let statusCalls = 0
    await page.route('**/github/status', (route) => {
      statusCalls += 1
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ connected: false }),
      })
    })

    await openImportPanel(page)
    await expect(page.getByTitle('Dashboard')).toBeVisible()
    await page.getByRole('button', { name: /^Import projects/i }).click()

    await expect(page.getByText(/GitHub isn't connected yet/i)).toBeVisible()
    expect(statusCalls).toBe(1)
  })
})
